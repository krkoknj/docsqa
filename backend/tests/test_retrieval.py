import asyncio

from langchain_core.documents import Document

from app.rag.retriever import RRF_K, HybridRetriever, fuse
from app.rag.tokenize import to_tsquery, tokenize


def test_tokenize_splits_hangul_into_bigrams_so_particles_still_match():
    assert tokenize("장애의 등급") == ["장애", "애의", "등급"]
    assert "장애" in tokenize("SEV2 장애가 발생")


def test_tokenize_keeps_latin_and_numbers_whole_and_lowercased():
    assert tokenize("PLT-E403 에러, SEV2!") == ["plt", "e403", "에러", "sev2"]


def test_tokenize_keeps_single_hangul_syllable():
    assert tokenize("몇 번") == ["몇", "번"]


def test_to_tsquery_ors_unique_tokens_and_handles_empty():
    assert to_tsquery("장애 장애 SEV2") == "장애 | sev2"
    assert to_tsquery("?!") is None


def doc(id_):
    return Document(id=id_, page_content=id_)


def test_fuse_rewards_chunks_found_by_both_retrievers():
    fused = fuse([doc("a"), doc("b")], [doc("b"), doc("c")])

    assert [c.doc.id for c in fused] == ["b", "a", "c"]
    b = fused[0]
    assert (b.vector_rank, b.keyword_rank) == (2, 1)
    assert b.fused_score == 1 / (RRF_K + 2) + 1 / (RRF_K + 1)


def test_fuse_with_single_list_preserves_order():
    fused = fuse([], [doc("x"), doc("y")])
    assert [c.doc.id for c in fused] == ["x", "y"]
    assert fused[0].vector_rank is None


def test_empty_document_scope_searches_nothing():
    """A user with no documents must never fall through to an unfiltered search."""

    class ExplodingStore:
        async def asimilarity_search_with_score(self, *args, **kwargs):
            raise AssertionError("searched without a document filter")

    retriever = HybridRetriever(ExplodingStore(), engine=None, table="chunks", mode="hybrid")
    result = asyncio.run(retriever.search("anything", k=4, document_ids=[]))
    assert result.candidates == []
