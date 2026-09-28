# RAG 평가 결과 — 2026-09-28 14:26

- 코퍼스: `samples/*.md` → 청크 36개 (chunk_size=400, overlap=80)
- 질문: 답이 있는 질문 34개로 검색 평가, k=4

## 검색 품질

| 구성 | Hit@1 | Hit@k | MRR | Hit@k (distractor) | Hit@k (keyword) | Hit@k (paraphrase) | 검색 지연 (중앙값) |
|---|---|---|---|---|---|---|---|
| `vector` | 74% | 88% | 0.809 | 100% | 85% | 86% | 195 ms |
| `hybrid` | 85% | 97% | 0.904 | 100% | 92% | 100% | 201 ms |
| `hybrid+llm` | 100% | 100% | 1.000 | 100% | 100% | 100% | 1542 ms |

놓친 질문:

- `vector`: hb-06, hr-05, rel-01, rel-05
- `hybrid`: rel-05
- `hybrid+llm`: 없음

## 전체 파이프라인 (RAGAS)

| 구성 | Faithfulness | Answer correctness | Context recall | 답변 거부 정확도 | 재검색 비율 | 응답 시간 (중앙값) |
|---|---|---|---|---|---|---|
| `vector` | 0.961 | 0.776 | 0.912 | 67% | 14% | 4.3 s |
| `hybrid` | 0.966 | 0.854 | 1.000 | 100% | 8% | 3.8 s |
| `hybrid+llm` | 0.971 | 0.853 | 1.000 | 100% | 5% | 5.3 s |
