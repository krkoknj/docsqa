# DocsQA — 문서 기반 RAG 질의응답 에이전트

PDF·Markdown 문서를 업로드하면, 문서 내용을 근거로 출처를 인용하며 답변하는 풀스택 AI 애플리케이션입니다.

- **Frontend**: Next.js 16 (App Router) · TypeScript · Tailwind CSS v4
- **Backend**: FastAPI · LangGraph · LangChain · OpenAI
- **Database**: PostgreSQL + pgvector
- **Infra**: Docker Compose

## 아키텍처

```
┌──────────────┐   REST (업로드/목록/삭제)   ┌──────────────────────────────┐
│  Next.js     │ ─────────────────────────▶ │  FastAPI + LangGraph          │
│  - 스트리밍 채팅 │   SSE (step/sources/token)  │  (Corrective RAG 그래프)       │
│  - 단계 타임라인 │ ◀───────────────────────── │                              │
│  - 출처·근거 표시 │                            └──────────────┬───────────────┘
└──────────────┘                                            │ asyncpg
                                              ┌─────────────▼───────────┐
                                              │ PostgreSQL + pgvector   │
                                              └─────────────────────────┘
```

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
cp backend/.env.example backend/.env         # OPENAI_API_KEY 입력
cp frontend/.env.example frontend/.env.local
```

### 2-A. 전체를 Docker로 실행 (가장 간단)
```bash
docker compose up -d --build     # db + backend + frontend
docker compose logs -f backend   # 로그 보기
docker compose down              # 종료 (DB 데이터는 볼륨에 유지)
```
- 앱: http://localhost:3000 · API 문서: http://localhost:8000/docs

### 2-B. 로컬 개발 (코드 수정 시 자동 반영)
```bash
docker compose up -d db                      # pgvector만 실행
cd backend && uv sync && uv run uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

## 테스트
```bash
cd backend && uv run pytest        # 청킹, SSE 규약, 그래프 분기 전체 (Fake LLM/Judge, DB·API 키 불필요)
cd backend && uv run ruff check .
cd frontend && npm run lint && npx tsc --noEmit
```

## 로드맵
- [x] **1단계 MVP**: 업로드·인덱싱, LangGraph RAG, SSE 스트리밍 채팅, 출처 인용 UI
- [x] **2단계 에이전트화**: 문서 관련성 평가 → 질문 재작성/재검색 → 환각 검사 및 재생성 (Corrective RAG + Self-RAG)
- [x] **3단계 검색 품질**: 하이브리드 검색(한글 bigram 전문 검색 + 벡터, RRF), 리랭커 비교, 평가 데이터셋 + RAGAS
- [ ] **4단계 완성도**: 인증, 비동기 인덱싱 큐, 대화 저장(LangGraph checkpointer), CI/CD, 배포
