"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamChat, type HistoryMessage, type Source } from "@/lib/api";
import SourceList from "./SourceList";
import GroundingBadge from "./GroundingBadge";
import StepIndicator, { applyStep, type Step } from "./StepIndicator";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  steps?: Step[];
  grounded?: boolean | null;
  error?: string;
  streaming?: boolean;
};

const HISTORY_LIMIT = 10;
const EXAMPLES = ["이 문서의 핵심 내용을 요약해줘", "중요한 규칙을 알려줘", "처음 읽는 사람이 알아야 할 것은?"];

/** Turn "[1]" citations into links so they can be clicked to open the source. */
function linkCitations(text: string) {
  return text.replace(/\[(\d+)\](?!\()/g, "[\\[$1\\]](#source-$1)");
}

export default function Chat({ documentIds }: { documentIds: string[] }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [activeSource, setActiveSource] = useState<Record<string, number | null>>({});
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const isStreaming = messages.some((m) => m.streaming);

  useEffect(() => {
    if (messages.length) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  function patch(id: string, update: (m: Message) => Partial<Message>) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...update(m) } : m)));
  }

  async function send(question: string) {
    question = question.trim();
    if (!question || isStreaming) return;

    const history: HistoryMessage[] = messages
      .filter((m) => !m.error && m.content)
      .slice(-HISTORY_LIMIT)
      .map(({ role, content }) => ({ role, content }));

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: question },
      { id: assistantId, role: "assistant", content: "", steps: [], streaming: true },
    ]);
    setInput("");

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const stream = streamChat(
        { question, history, document_ids: documentIds.length ? documentIds : null },
        controller.signal,
      );
      for await (const ev of stream) {
        switch (ev.event) {
          case "step":
            patch(assistantId, (m) => ({ steps: applyStep(m.steps ?? [], ev.data) }));
            break;
          case "sources":
            patch(assistantId, () => ({ sources: ev.data }));
            break;
          case "reset":
            // The grounding check rejected the answer; a new one is about to stream.
            patch(assistantId, () => ({ content: "" }));
            break;
          case "token":
            patch(assistantId, (m) => ({ content: m.content + ev.data.text }));
            break;
          case "done":
            patch(assistantId, () => ({ grounded: ev.data.grounded }));
            break;
          case "error":
            patch(assistantId, () => ({ error: ev.data.message }));
            break;
        }
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        patch(assistantId, () => ({ error: (e as Error).message || "서버에 연결할 수 없습니다." }));
      }
    } finally {
      patch(assistantId, () => ({ streaming: false }));
      abortRef.current = null;
    }
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-8 px-5 py-8 md:px-8">
          {messages.length === 0 && (
            <div className="animate-rise mt-6 flex flex-col gap-8 md:mt-20">
              <h1 className="text-4xl leading-[1.1] font-light tracking-[-0.03em] md:text-6xl">
                docsqa는 문서가
                <br />
                <strong className="font-bold">직접 대답하는</strong> 공간입니다.
              </h1>
              <p className="max-w-md text-lg font-light text-cream-dim">
                문서를 올리고 질문하세요. 모든 답변에는 근거가 된 원문이 함께 달립니다.
              </p>
              <div className="flex flex-wrap gap-2.5">
                {EXAMPLES.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => send(q)}
                    className="rounded-full border border-ink-line px-5 py-2.5 text-sm transition-colors hover:border-blush hover:bg-blush hover:text-ink"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <div
                key={m.id}
                className="animate-rise max-w-[85%] self-end rounded-[1.75rem] rounded-br-md bg-blush px-5 py-3 whitespace-pre-wrap text-ink"
              >
                {m.content}
              </div>
            ) : (
              <article key={m.id} className="animate-rise flex flex-col gap-4">
                <StepIndicator steps={m.steps ?? []} />
                {m.content && (
                  <div className="prose prose-docsqa max-w-none text-[16px] leading-relaxed font-light prose-strong:font-bold prose-code:rounded-md prose-code:bg-ink prose-code:px-1.5 prose-code:py-0.5 prose-code:font-normal prose-code:before:content-none prose-code:after:content-none">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        a: ({ href, children }) =>
                          href?.startsWith("#source-") ? (
                            <button
                              type="button"
                              onClick={() =>
                                setActiveSource((s) => ({ ...s, [m.id]: Number(href.slice(8)) }))
                              }
                              className="mx-0.5 rounded-full bg-lilac px-1.5 align-super text-[10px] font-bold text-ink transition-transform hover:scale-110"
                            >
                              {children}
                            </button>
                          ) : (
                            <a href={href} target="_blank" rel="noreferrer">
                              {children}
                            </a>
                          ),
                      }}
                    >
                      {linkCitations(m.content)}
                    </ReactMarkdown>
                    {m.streaming && (
                      <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-full bg-flame align-middle" />
                    )}
                  </div>
                )}
                {!m.streaming && <GroundingBadge grounded={m.grounded} />}
                {m.error && <p className="rounded-2xl bg-flame px-4 py-3 text-sm text-cream">{m.error}</p>}
                <SourceList
                  sources={m.sources ?? []}
                  activeId={activeSource[m.id] ?? null}
                  onSelect={(id) => setActiveSource((s) => ({ ...s, [m.id]: id }))}
                />
              </article>
            ),
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="px-5 pt-2 pb-5 md:px-8 md:pb-7"
      >
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-[2rem] border border-ink-line bg-ink-soft p-2 pl-6 transition-colors focus-within:border-cream">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder="질문을 입력하세요"
            aria-label="질문 입력 (Enter 전송, Shift+Enter 줄바꿈)"
            className="max-h-40 flex-1 resize-none self-center bg-transparent py-2 text-base font-light outline-none placeholder:text-cream-dim"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="flex h-12 items-center gap-2 rounded-full bg-cream px-5 font-bold text-ink"
            >
              <span className="size-2.5 rounded-sm bg-ink" />
              중지
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              className="flex h-12 items-center gap-3 rounded-full bg-flame pr-2 pl-5 font-bold text-cream transition-opacity disabled:opacity-35"
            >
              보내기
              <span className="grid size-8 place-items-center rounded-full bg-cream text-ink">→</span>
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
