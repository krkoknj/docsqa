# DocsQA — 문서 기반 RAG 질의응답 에이전트

[![CI](https://github.com/krkoknj/docsqa/actions/workflows/ci.yml/badge.svg)](https://github.com/krkoknj/docsqa/actions/workflows/ci.yml)

PDF·Markdown 문서를 업로드하면, 문서 내용을 근거로 출처를 인용하며 답변하는 풀스택 AI 애플리케이션입니다.

- **Frontend**: Next.js 16 (App Router) · TypeScript · Tailwind CSS v4
- **Backend**: FastAPI · LangGraph · LangChain · OpenAI
- **Database**: PostgreSQL + pgvector
- **Infra**: Docker Compose · GitHub Actions (CI, GHCR 이미지 배포) · Caddy (HTTPS)

## 아키텍처

```
 브라우저 ── https ──▶ Next.js ── /api/* 프록시 ──▶ FastAPI (API)  ─── SSE 스트리밍 채팅
                     (같은 출처라 httpOnly            │  · 로그인 (JWT 쿠키)
                      세션 쿠키가 그대로 동작)          │  · LangGraph Corrective RAG
                                                     │  · 대화 저장
                                                     ▼
                                          PostgreSQL + pgvector ◀── 색인 워커 (별도 프로세스)
                                          users · documents(=작업 큐)     SKIP LOCKED로 작업을 가져와
                                          chunks · conversations         파싱 → 청킹 → 임베딩
```

- **인증:** 이메일/비밀번호(argon2id) + JWT를 담은 **httpOnly, SameSite=Lax 쿠키**. 브라우저는 Next.js하고만 통신하고 `/api/*`는 백엔드로 프록시되므로, 쿠키가 항상 퍼스트 파티로 동작합니다.
- **사용자별 데이터 격리:** 문서, 대화, 검색이 모두 소유자 기준으로 제한됩니다. 사용자에게 문서가 없으면 검색 범위가 "전체"가 아니라 **"없음"**이 되도록 해서, 다른 사용자의 청크가 검색될 여지를 막았습니다. 통합 테스트로 검증합니다.
- **비동기 색인 큐:** 업로드는 파일을 저장하고 곧바로 `202`를 반환합니다. 색인 워커가 `documents` 테이블을 큐로 사용해 `FOR UPDATE SKIP LOCKED`로 작업을 가져가므로, **Redis 없이** 워커를 여러 개 띄울 수 있습니다. 재시도 횟수 제한, 멱등한 재색인, 죽은 워커의 작업 회수를 지원합니다.
- **데이터 무결성:** 청크는 `ON DELETE CASCADE` FK로 문서에 연결되어, 문서를 지우면 청크와 원본 파일이 함께 삭제됩니다. 스키마는 advisory lock으로 직렬화된 버전 마이그레이션으로 관리합니다.
- **대화 저장:** 대화와 메시지(출처, 근거 검증 결과 포함)를 서버에 저장합니다. 이전 대화 내용은 클라이언트가 보낸 값을 믿지 않고 DB에서 불러옵니다.

### LangGraph 파이프라인 (Corrective RAG + Self-RAG)

```
START → retrieve → grade ─(관련 문서 있음)──────────────▶ generate → check ─(근거 충분)──▶ END
           ▲          └─(없음 & 재시도 가능)→ rewrite ┐      ▲          │
           └────────────────────────────────────────┘      └─(근거 부족 & 재시도 가능)
```

| 노드 | 역할 | 구현 |
|---|---|---|
| `retrieve` | 하이브리드 검색 + 리랭킹 (아래 참고) | `HybridRetriever` |
| `grade` | 검색된 청크 중 **질문에 실제로 도움이 되는 것만** 선별 | LLM 구조화 출력 (`GradeResult`) |
| `rewrite` | 관련 문서가 없으면 검색어를 다시 써서 재검색 (최대 1회) | LLM 구조화 출력 (`RewriteResult`) |
| `generate` | 관련 청크만 컨텍스트로 넣고 출처 번호를 달아 답변 | 토큰 스트리밍 |
| `check` | 답변의 모든 주장이 출처로 뒷받침되는지 검증, 실패 시 피드백과 함께 재생성 (최대 2회 생성) | LLM 구조화 출력 (`GroundingResult`) |

- 평가 로직은 `Judges` 프로토콜 뒤에 있어서, 테스트에서는 결과를 미리 정해 둔 가짜 평가기로 **모든 분기(재검색, 재생성, 포기)를 결정적으로 검증**합니다.
- 반복 횟수 상한(`MAX_QUERY_REWRITES`, `MAX_GENERATIONS`)으로 무한 루프와 비용 폭주를 막습니다.

### 검색: 하이브리드 + 리랭킹

```
query ─┬─ 벡터 검색   (pgvector 코사인 거리, 상위 20) ──┐
       └─ 키워드 검색 (tsvector + 한글 bigram, 상위 20) ┴─ RRF 결합 ─ 상위 12 ─ LLM 리랭크 ─ 상위 4
```

- **키워드 검색:** PostgreSQL에는 한국어 형태소 사전이 없고, 한국어는 조사가 붙어서("장애의", "장애가") 단어 단위로는 잘 매칭되지 않습니다. 그래서 한글은 **2글자 단위(bigram)로 잘라 색인**합니다("장애의" → "장애", "애의"). 청크마다 토큰을 저장하고, `GENERATED` tsvector 컬럼과 GIN 인덱스로 검색합니다([tokenize.py](backend/app/rag/tokenize.py)).
- **RRF (Reciprocal Rank Fusion):** 점수 체계가 전혀 다른 두 검색 결과를 `Σ 1/(60 + 순위)`로 합칩니다. 점수를 정규화할 필요가 없습니다.
- **리랭킹 (선택):** 후보 12개를 LLM이 한 번의 구조화 호출로 0~10점 채점합니다. 평가 결과 최종 답변 품질 향상이 없어 기본값은 꺼 두었습니다(`RERANKER=llm`으로 켬).

### SSE 이벤트 규약 (`POST /api/chat`)
| event | data |
|---|---|
| `conversation` | `{ id, title }`, 첫 이벤트. 새 질문이면 서버가 대화를 만들어 알려줌 |
| `step` | `{ node, status: "start" \| "end", detail }`, 노드는 반복될 수 있음 |
| `sources` | `[{ id, document_id, source, page, score, content, relevant? }]`, 검색 직후 1번, 평가 후 `relevant`를 붙여 다시 1번 |
| `reset` | `{}`, 근거 검증 실패로 지금까지 받은 답변을 버리고 재생성 |
| `token` | `{ text }` |
| `done` | `{ answer, grounded: true \| false \| null }` |
| `error` | `{ message }` |

## 평가 결과

[backend/eval](backend/eval)에 평가 데이터셋과 스크립트가 있습니다.
- **코퍼스:** 가상 사내 문서 5종([samples/](samples)), 36개 청크
- **질문:** 37개 (키워드형, 바꿔 말하기형, 헷갈리는 문서가 섞인 유형, 답이 없는 질문 3개)

```bash
cd backend
uv run --group eval python -m eval.run_eval          # 검색 지표만 (빠르고 저렴)
uv run --group eval python -m eval.run_eval --e2e    # + 전체 파이프라인 RAGAS 지표
```

### 검색 품질 (청크 400자, k=4)

| 구성 | Hit@1 | Hit@4 | MRR | 검색 지연 |
|---|---|---|---|---|
| 벡터 검색 (2단계) | 74% | 88% | 0.809 | 212 ms |
| 키워드 검색 (한글 bigram) | 85% | 97% | 0.904 | **3 ms** |
| **하이브리드 (RRF)** | 85% | 97% | 0.904 | 217 ms |
| 하이브리드 + LLM 리랭커 | **100%** | **100%** | **1.000** | 1,689 ms |
| 하이브리드 + 크로스인코더 (FlashRank MultiBERT) | 6% | 32% | 0.174 | 1,480 ms |

### 전체 파이프라인 (RAGAS, LLM 채점)

| 구성 | Faithfulness | Answer correctness | Context recall | 답이 없을 때 거부 | 응답 시간 |
|---|---|---|---|---|---|
| 벡터 검색 (2단계) | 0.961 | 0.776 | 0.912 | 67% | 4.3 s |
| **하이브리드 (현재 기본값)** | 0.966 | **0.854** | **1.000** | **100%** | **3.8 s** |
| 하이브리드 + LLM 리랭커 | 0.971 | 0.853 | 1.000 | 100% | 5.3 s |

### 결과에서 내린 결정
- **하이브리드 검색 도입:** 벡터 검색만 쓸 때보다 Answer correctness가 **0.776 → 0.854 (+10%)**로 올랐습니다. 벡터 검색이 놓친 `PLT-2231` 같은 **고유 식별자** 질문을 키워드 검색이 찾아냈습니다. 단, "지금 진단할 수 있는 식물은 몇 종이야?"(정답: 2,050종)는 하이브리드도 상위 4개 안에 찾아오지 못했습니다.
- **LLM 리랭커는 기본값에서 제외:** 검색 순위는 완벽해졌지만 최종 답변 품질은 같고 응답만 1.5초 느려졌습니다. 2단계의 `grade` 노드가 이미 LLM으로 관련 청크를 걸러내기 때문에 효과가 겹칩니다. 문서가 훨씬 많아지면 다시 측정할 가치가 있습니다.
- **경량 크로스인코더는 사용하지 않음:** 다국어 모델인데도 한국어에서 무작위(33%)보다 낮았습니다. 점수가 0.9995~0.9997로 거의 구분되지 않았고, 1000자 청크는 512토큰에서 잘렸습니다.
- **청크 크기 1000 → 400자:** 벡터 검색 Hit@1이 71% → 74%, 하이브리드는 71% → 85%로 올랐고, 출처도 더 정확하게 가리킵니다. 결과 파일은 [eval/results/](backend/eval/results)에 있습니다.

### 평가의 한계
- 질문이 34개(+답 없는 질문 3개)로 적고, 1회 실행 결과라 **±수 %p 차이는 오차 범위**입니다.
- 질문과 문서를 같은 사람이 작성해서, 표현이 겹치는 키워드 검색에 유리했을 수 있습니다.
- RAGAS 채점 모델이 생성 모델과 같은 계열(gpt-4.1-mini)입니다.

## 실행 방법

### 1. 환경 변수
```bash
cp backend/.env.example backend/.env         # OPENAI_API_KEY, JWT_SECRET 입력
cp frontend/.env.example frontend/.env.local
```

### 2-A. 전체를 Docker로 실행 (가장 간단)
```bash
docker compose up -d --build            # db + backend + worker + frontend
docker compose up -d --scale worker=3   # 색인 워커 늘리기
docker compose logs -f backend worker   # 로그 보기
docker compose down                     # 종료 (DB 데이터는 볼륨에 유지)
```
- 앱: http://localhost:3000 (회원가입 후 사용) · API 문서: http://localhost:8000/docs

### 2-B. 로컬 개발 (코드 수정 시 자동 반영)
```bash
docker compose up -d db                      # pgvector만 실행
cd backend && uv sync && uv run uvicorn app.main:app --reload   # 색인 워커가 API 안에서 함께 실행됨
cd frontend && npm install && npm run dev
```

## 테스트
```bash
docker compose up -d db
cd backend && uv run pytest
cd backend && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run lint && npx tsc --noEmit
```
- **단위 테스트:** 청킹, 토크나이저, RRF, 그래프의 모든 분기(가짜 LLM/평가기 사용)
- **통합 테스트:** 임시 DB(`rag_test`)에 실제 앱을 띄워 검증합니다. 회원가입·로그인, 사용자 간 격리, 색인 워커, 실패 후 재시도, 삭제 cascade, 대화 저장이 대상이고, 모델은 가짜라 API 키가 필요 없습니다. Postgres가 없으면 자동으로 건너뜁니다.
- **CI:** GitHub Actions가 push와 PR마다 pgvector 서비스 컨테이너를 붙여 위 테스트 전체와 프론트엔드 빌드, Docker 이미지 빌드를 실행합니다.

## 배포

`main`에서 CI가 통과하면 [release.yml](.github/workflows/release.yml)이 Docker 이미지를 GitHub Container Registry에 게시합니다(`ghcr.io/krkoknj/docsqa-backend`, `docsqa-frontend`). Docker가 있는 서버라면 어디든 배포할 수 있습니다.

```bash
cp deploy/.env.example deploy/.env   # 도메인, OpenAI 키, JWT_SECRET, DB 비밀번호
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d
```
- 외부에는 Caddy만 노출되고, Let's Encrypt로 HTTPS 인증서가 자동 발급됩니다. 쿠키는 `Secure`로 설정됩니다.
- 필수 비밀값이 비어 있으면 compose가 시작 단계에서 오류를 냅니다.

## 로드맵
- [x] **1단계 MVP**: 업로드·인덱싱, LangGraph RAG, SSE 스트리밍 채팅, 출처 인용 UI
- [x] **2단계 에이전트화**: 문서 관련성 평가 → 질문 재작성/재검색 → 환각 검사 및 재생성 (Corrective RAG + Self-RAG)
- [x] **3단계 검색 품질**: 하이브리드 검색(한글 bigram 전문 검색 + 벡터, RRF), 리랭커 비교, 평가 데이터셋 + RAGAS
- [x] **4단계 완성도**: 회원가입·로그인, 사용자별 데이터 격리, Postgres 기반 비동기 색인 큐, 대화 저장, 통합 테스트, CI/CD(GHCR), 프로덕션 compose + HTTPS

### 다음에 개선할 점
- **이어지는 질문의 검색어:** "그 에러는 어떻게 해결해?"처럼 앞 대화를 가리키는 질문은 그대로 검색되어 관련 문서를 놓칠 수 있습니다. 대화 맥락을 반영해 검색어를 다시 쓰는 단계를 추가할 계획입니다.
- 로그인 시도 횟수 제한(rate limit), 비밀번호 재설정
- 대화 저장에 LangGraph checkpointer 대신 전용 테이블을 쓴 이유: 사이드바 목록 조회와 사용자별 권한 검사가 SQL 한 번으로 끝나고, 그래프는 한 번의 질문을 처리하는 단위로 단순하게 유지할 수 있기 때문입니다.
