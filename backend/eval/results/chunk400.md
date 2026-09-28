# RAG 평가 결과 — 2026-09-28 14:17

- 코퍼스: `samples/*.md` → 청크 36개 (chunk_size=400, overlap=80)
- 질문: 답이 있는 질문 34개로 검색 평가, k=4

## 검색 품질

| 구성 | Hit@1 | Hit@k | MRR | Hit@k (distractor) | Hit@k (keyword) | Hit@k (paraphrase) | 검색 지연 (중앙값) |
|---|---|---|---|---|---|---|---|
| `vector` | 74% | 88% | 0.809 | 100% | 85% | 86% | 212 ms |
| `keyword` | 85% | 97% | 0.904 | 100% | 92% | 100% | 3 ms |
| `hybrid` | 85% | 97% | 0.904 | 100% | 92% | 100% | 217 ms |
| `hybrid+cross-encoder` | 6% | 32% | 0.174 | 29% | 46% | 21% | 1480 ms |
| `hybrid+llm` | 100% | 100% | 1.000 | 100% | 100% | 100% | 1689 ms |

놓친 질문:

- `vector`: hb-06, hr-05, rel-01, rel-05
- `keyword`: rel-05
- `hybrid`: rel-05
- `hybrid+cross-encoder`: hb-01, hb-02, hb-03, hb-04, hb-06, hb-08, sec-01, sec-03, sec-04, sec-05, sec-07, sec-08, api-02, api-03, api-04, api-06, hr-01, hr-03, hr-05, rel-01, rel-02, rel-03, rel-04
- `hybrid+llm`: 없음
