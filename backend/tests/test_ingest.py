from uuid import uuid4

import pytest

from app.rag.graph import format_context, relevant_sources
from app.rag.ingest import UnsupportedFileError, load_pages, split_into_chunks


def test_load_pages_reads_text_files():
    pages = load_pages("note.md", "# 제목\n본문".encode())
    assert pages == [(None, "# 제목\n본문")]


def test_load_pages_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileError):
        load_pages("image.png", b"\x89PNG")


def test_split_into_chunks_attaches_metadata_and_sequential_index():
    doc_id = uuid4()
    pages = [(1, "가" * 250), (2, "나" * 250)]

    chunks = split_into_chunks(doc_id, "a.pdf", pages, chunk_size=100, chunk_overlap=0)

    assert len(chunks) == 6
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(6))
    assert {c.metadata["page"] for c in chunks} == {1, 2}
    assert all(c.metadata["document_id"] == str(doc_id) for c in chunks)
    assert chunks[0].metadata["search_tokens"].startswith("가가")


def test_split_into_chunks_skips_empty_pages():
    chunks = split_into_chunks(uuid4(), "a.pdf", [(1, "   "), (2, "")], chunk_size=100, chunk_overlap=0)
    assert chunks == []


def test_format_context_numbers_sources_with_location():
    context = format_context(
        [
            {
                "id": 1,
                "document_id": "x",
                "source": "guide.pdf",
                "page": 3,
                "score": 0.1,
                "vector_rank": 1,
                "keyword_rank": None,
                "rerank_score": None,
                "content": "hello",
            }
        ]
    )
    assert context == "[1] (guide.pdf p.3)\nhello"


def test_relevant_sources_keeps_only_flagged_chunks():
    state = {"sources": [{"id": 1, "relevant": True}, {"id": 2, "relevant": False}, {"id": 3}]}
    assert [s["id"] for s in relevant_sources(state)] == [1]
