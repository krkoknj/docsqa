"use client";

import { useRef, useState } from "react";
import { deleteDocument, uploadDocument, type DocumentInfo } from "@/lib/api";

type Props = {
  documents: DocumentInfo[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onChange: () => void;
};

const ACCEPT = ".pdf,.md,.txt";

// Each document gets a color block + a slight tilt, cycling through the palette.
const CARD_STYLES = [
  "bg-sky text-ink -rotate-1",
  "bg-mustard text-ink rotate-1",
  "bg-forest text-cream -rotate-[0.5deg]",
  "bg-lilac text-ink rotate-[0.75deg]",
  "bg-flame text-cream -rotate-[0.75deg]",
  "bg-blush text-ink rotate-[0.5deg]",
];

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DocumentPanel({ documents, selectedIds, onToggle, onChange }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    setError(null);
    for (const file of Array.from(files)) {
      setUploading(file.name);
      try {
        await uploadDocument(file);
      } catch (e) {
        setError(`${file.name}: ${(e as Error).message}`);
      }
    }
    setUploading(null);
    onChange();
  }

  async function handleDelete(doc: DocumentInfo) {
    if (!confirm(`"${doc.filename}" 문서를 삭제할까요?`)) return;
    try {
      await deleteDocument(doc.id);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <aside className="flex w-full flex-col gap-6 p-5 md:h-full md:w-[22rem] md:p-7">
      <header>
        <p className="text-5xl leading-none font-bold tracking-[-0.04em]">docsqa</p>
        <p className="mt-3 text-sm font-light text-cream-dim">문서와 대화가 만나는 공간</p>
      </header>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        disabled={!!uploading}
        className={`group flex flex-col items-start gap-1 rounded-[2rem] border px-6 py-5 text-left transition-all ${
          dragging
            ? "scale-[1.02] border-blush bg-blush text-ink"
            : "border-ink-line hover:border-cream"
        } disabled:cursor-wait`}
      >
        {uploading ? (
          <>
            <span className="text-lg font-bold">인덱싱 중…</span>
            <span className="w-full truncate text-sm font-light animate-pulse">{uploading}</span>
          </>
        ) : (
          <>
            <span className="flex w-full items-center justify-between text-lg font-bold">
              문서 올리기
              <span className="grid size-8 place-items-center rounded-full bg-cream text-ink transition-transform group-hover:rotate-90">
                +
              </span>
            </span>
            <span className={`text-sm font-light ${dragging ? "" : "text-cream-dim"}`}>
              끌어다 놓거나 클릭 · PDF, MD, TXT · 10MB
            </span>
          </>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = "";
        }}
      />

      {error && <p className="rounded-2xl bg-flame px-4 py-3 text-sm text-cream">{error}</p>}

      <div className="flex min-h-0 flex-1 flex-col gap-3">
        <div className="flex items-baseline justify-between px-1">
          <span className="text-sm font-bold">내 문서 {documents.length}</span>
          <span className="text-xs font-light text-cream-dim">
            {selectedIds.size ? `${selectedIds.size}개 선택됨` : "전체에서 검색"}
          </span>
        </div>
        <ul className="-mx-1 flex max-h-56 flex-col gap-2.5 overflow-y-auto px-1 py-1 md:max-h-none">
          {documents.length === 0 && (
            <li className="rounded-[1.5rem] border border-dashed border-ink-line px-5 py-4 text-sm font-light text-cream-dim">
              아직 문서가 없어요.
            </li>
          )}
          {documents.map((doc, i) => {
            const selected = selectedIds.has(doc.id);
            return (
              <li
                key={doc.id}
                className={`group relative rounded-[1.5rem] transition-transform hover:rotate-0 ${CARD_STYLES[i % CARD_STYLES.length]} ${
                  selected ? "ring-2 ring-cream ring-offset-2 ring-offset-ink" : ""
                }`}
              >
                <label className="flex cursor-pointer items-center gap-3 py-3.5 pr-14 pl-5">
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => onToggle(doc.id)}
                    className="peer sr-only"
                    aria-label={`${doc.filename} 검색 범위에 포함`}
                  />
                  <span
                    aria-hidden
                    className="grid size-5 shrink-0 place-items-center rounded-full border-2 border-current text-[10px] font-bold peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2"
                  >
                    {selected ? "✓" : ""}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-bold" title={doc.filename}>
                      {doc.filename}
                    </span>
                    <span className="block text-xs font-light opacity-80">
                      {formatSize(doc.size_bytes)} · 청크 {doc.chunk_count}개
                    </span>
                  </span>
                </label>
                <button
                  type="button"
                  onClick={() => handleDelete(doc)}
                  aria-label={`${doc.filename} 삭제`}
                  className="absolute top-1/2 right-3 grid size-8 -translate-y-1/2 place-items-center rounded-full opacity-0 transition-opacity group-hover:opacity-100 hover:bg-ink hover:text-cream focus:opacity-100"
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
