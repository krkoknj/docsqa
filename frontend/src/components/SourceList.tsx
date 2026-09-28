import type { Source } from "@/lib/api";

type Props = {
  sources: Source[];
  activeId: number | null;
  onSelect: (id: number | null) => void;
};

export default function SourceList({ sources, activeId, onSelect }: Props) {
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-col gap-2.5">
      <ul className="flex flex-wrap items-center gap-2">
        <li className="mr-1 text-xs font-bold tracking-wide text-cream-dim uppercase">Sources</li>
        {sources.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onSelect(activeId === s.id ? null : s.id)}
              aria-pressed={activeId === s.id}
              title={s.relevant === false ? "관련성 평가에서 제외된 조각" : undefined}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                activeId === s.id
                  ? "border-lilac bg-lilac text-ink"
                  : s.relevant === false
                    ? "border-dashed border-ink-line text-cream-dim line-through hover:border-cream-dim"
                    : "border-ink-line text-cream hover:border-cream"
              }`}
            >
              <span className="font-bold">{s.id}</span> · {s.source}
              {s.page ? ` p.${s.page}` : ""}
            </button>
          </li>
        ))}
      </ul>
      {activeId !== null && <SourcePreview source={sources.find((s) => s.id === activeId)} />}
    </div>
  );
}

function SourcePreview({ source }: { source?: Source }) {
  if (!source) return null;
  return (
    <figure className="animate-rise rounded-[1.75rem] bg-sky p-6 text-ink">
      <figcaption className="mb-3 flex items-baseline justify-between gap-4">
        <span className="text-xl font-bold tracking-tight">
          [{source.id}] {source.source}
          {source.page ? ` · ${source.page}쪽` : ""}
        </span>
        {source.relevant === false && <span className="shrink-0 font-mono text-xs opacity-70">제외됨</span>}
      </figcaption>
      <RetrievalBadges source={source} />
      <blockquote className="max-h-64 overflow-y-auto text-[15px] leading-relaxed font-light whitespace-pre-wrap">
        {source.content}
      </blockquote>
    </figure>
  );
}

/** How this chunk was found: which retrievers ranked it, and the reranker's verdict. */
function RetrievalBadges({ source }: { source: Source }) {
  const badges = [
    source.vector_rank && `벡터 #${source.vector_rank}`,
    source.keyword_rank && `키워드 #${source.keyword_rank}`,
    source.rerank_score !== null && `리랭크 ${source.rerank_score}/10`,
  ].filter(Boolean);
  if (badges.length === 0) return null;
  return (
    <ul className="mb-3 flex flex-wrap gap-1.5" aria-label="검색 경로">
      {badges.map((b) => (
        <li key={b as string} className="rounded-full bg-ink/15 px-2.5 py-0.5 font-mono text-[11px] font-bold">
          {b}
        </li>
      ))}
    </ul>
  );
}
