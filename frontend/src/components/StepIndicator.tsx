import type { GraphNode, StepEvent } from "@/lib/api";

export type Step = { node: GraphNode; status: "running" | "done"; detail: string | null };

const NODES: Record<GraphNode, { label: string; color: string }> = {
  retrieve: { label: "문서 검색", color: "bg-sky text-ink border-sky" },
  grade: { label: "관련성 평가", color: "bg-mustard text-ink border-mustard" },
  rewrite: { label: "검색어 재작성", color: "bg-lilac text-ink border-lilac" },
  generate: { label: "답변 생성", color: "bg-flame text-cream border-flame" },
  check: { label: "근거 검증", color: "bg-forest text-cream border-forest" },
};

/** Fold a step event into the timeline. Nodes can repeat (rewrite loop, regeneration). */
export function applyStep(steps: Step[], ev: StepEvent): Step[] {
  if (ev.status === "start") return [...steps, { node: ev.node, status: "running", detail: ev.detail }];

  const i = steps.findLastIndex((s) => s.node === ev.node && s.status === "running");
  if (i === -1) return [...steps, { node: ev.node, status: "done", detail: ev.detail }];
  return steps.map((s, j) => (j === i ? { ...s, status: "done", detail: ev.detail ?? s.detail } : s));
}

export default function StepIndicator({ steps }: { steps: Step[] }) {
  if (steps.length === 0) {
    return <p className="text-xs font-bold text-fg-dim animate-pulse">준비 중…</p>;
  }
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="에이전트 진행 상태">
      {steps.map((step, i) => {
        const { label, color } = NODES[step.node];
        return (
          <li key={i} className="flex max-w-full items-center gap-1.5">
            {i > 0 && <span className="text-fg-dim">→</span>}
            <span
              title={step.detail ?? undefined}
              className={`flex max-w-72 items-center gap-1.5 rounded-full border px-3 py-1 ${color} ${
                step.status === "running" ? "opacity-90" : ""
              }`}
            >
              {step.status === "running" ? (
                <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-current" />
              ) : (
                <span aria-hidden>✓</span>
              )}
              <span className="shrink-0 font-bold">{label}</span>
              {step.detail && <span className="truncate font-light">· {step.detail}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
