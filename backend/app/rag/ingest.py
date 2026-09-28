import io
from pathlib import Path
from uuid import UUID

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.rag.tokenize import to_search_text

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".txt"}


class UnsupportedFileError(ValueError):
    pass


def load_pages(filename: str, data: bytes) -> list[tuple[int | None, str]]:
    """Extract text as (page_number, text) pairs. Non-PDF files are a single page=None."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"지원하지 않는 파일 형식입니다: {ext or '(확장자 없음)'}")

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]

    return [(None, data.decode("utf-8", errors="replace"))]


def split_into_chunks(
    document_id: UUID,
    filename: str,
    pages: list[tuple[int | None, str]],
    chunk_size: int,
    chunk_overlap: int,
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: list[Document] = []
    for page, content in pages:
        for piece in splitter.split_text(content):
            if not piece.strip():
                continue
            chunks.append(
                Document(
                    page_content=piece,
                    metadata={
                        "document_id": str(document_id),
                        "source": filename,
                        "page": page,
                        "chunk_index": len(chunks),
                        "search_tokens": to_search_text(piece),
                    },
                )
            )
    return chunks
