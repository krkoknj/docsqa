"use client";

import { useState } from "react";
import { deleteConversation, type Conversation } from "@/lib/api";

type Props = {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string | null) => void;
  onChange: () => void;
};

function relativeTime(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "방금";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return new Date(iso).toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}

export default function ConversationList({ conversations, activeId, onSelect, onChange }: Props) {
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function remove(id: string) {
    setPendingDelete(null);
    setError(null);
    try {
      await deleteConversation(id);
      if (id === activeId) onSelect(null);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="flex items-center justify-between rounded-[2rem] border border-ink-line px-6 py-4 text-lg font-bold transition-colors hover:border-cream"
      >
        새 대화
        <span className="grid size-8 place-items-center rounded-full bg-cream text-ink">+</span>
      </button>

      {error && <p className="rounded-2xl bg-flame px-4 py-3 text-sm text-cream">{error}</p>}

      <ul className="-mx-1 flex max-h-56 flex-col gap-1 overflow-y-auto px-1 py-1 md:max-h-none">
        {conversations.length === 0 && (
          <li className="px-2 py-3 text-sm font-light text-cream-dim">아직 대화가 없어요.</li>
        )}
        {conversations.map((c) => {
          const active = c.id === activeId;
          return (
            <li key={c.id} className="group relative">
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={active ? "page" : undefined}
                className={`flex w-full flex-col items-start rounded-2xl py-2.5 pr-12 pl-4 text-left transition-colors ${
                  active ? "bg-lilac text-ink" : "hover:bg-ink-soft"
                }`}
              >
                <span className="w-full truncate text-sm font-bold">{c.title}</span>
                <span className={`text-xs font-light ${active ? "opacity-70" : "text-cream-dim"}`}>
                  {relativeTime(c.updated_at)}
                </span>
              </button>
              {pendingDelete === c.id ? (
                <div className="absolute inset-y-0 right-1 flex items-center gap-1">
                  <button
                    type="button"
                    autoFocus
                    onClick={() => remove(c.id)}
                    onKeyDown={(e) => e.key === "Escape" && setPendingDelete(null)}
                    className="rounded-full bg-flame px-3 py-1 text-xs font-bold text-cream"
                  >
                    삭제
                  </button>
                  <button
                    type="button"
                    onClick={() => setPendingDelete(null)}
                    className="rounded-full bg-ink px-2 py-1 text-xs font-bold text-cream"
                  >
                    취소
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setPendingDelete(c.id)}
                  aria-label={`${c.title} 대화 삭제`}
                  className={`absolute top-1/2 right-2 grid size-8 -translate-y-1/2 place-items-center rounded-full opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-60 ${
                    active ? "text-ink hover:bg-ink/15" : "hover:bg-ink"
                  }`}
                >
                  ✕
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
