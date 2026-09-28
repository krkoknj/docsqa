# RAG 평가 결과 — 2026-09-28 14:14

- 코퍼스: `samples/*.md` → 청크 14개 (chunk_size=1000, overlap=150)
- 질문: 답이 있는 질문 34개로 검색 평가, k=4

## 검색 품질

| 구성 | Hit@1 | Hit@k | MRR | Hit@k (distractor) | Hit@k (keyword) | Hit@k (paraphrase) | 검색 지연 (중앙값) |
|---|---|---|---|---|---|---|---|
| `vector` | 71% | 91% | 0.794 | 100% | 92% | 86% | 195 ms |
| `keyword` | 82% | 100% | 0.900 | 100% | 100% | 100% | 2 ms |
| `hybrid` | 71% | 100% | 0.841 | 100% | 100% | 100% | 198 ms |
| `hybrid+cross-encoder` | 9% | 29% | 0.164 | 29% | 31% | 29% | 1601 ms |
| `hybrid+llm` | 94% | 100% | 0.971 | 100% | 100% | 100% | 1738 ms |

놓친 질문:

- `vector`: hb-06, sec-02, rel-05
- `keyword`: 없음
- `hybrid`: 없음
- `hybrid+cross-encoder`: hb-01, hb-02, hb-03, hb-04, hb-05, hb-06, hb-07, hb-08, hb-09, hb-10, sec-03, sec-04, sec-05, sec-07, api-01, api-06, hr-02, hr-03, hr-05, rel-01, rel-02, rel-03, rel-04, rel-05
- `hybrid+llm`: 없음
