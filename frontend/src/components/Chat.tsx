"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getConversation, streamChat, UnauthorizedError, type Source, type StoredMessage } from "@/lib/api";
import SourceList from "./SourceList";
import GroundingBadge from "./GroundingBadge";
import StepIndicator, { applyStep, type Step } from "./StepIndicator";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  /** Only present for turns streamed in this session; stored messages don't keep the timeline. */
  steps?: Step[];
  grounded?: boolean | null;
  error?: string;
  streaming?: boolean;
};

type Props = {
  conversationId: string | null;
  documentIds: string[];
  /** Called when the server creates a conversation for the first question. */
  onConversationStarted: (id: string) => void;
  /** Called after each answer finishes (to refresh the conversation list). */
  onTurnComplete: () => void;
  onUnauthorized: () => void;
};

const EXAMPLES = ["이 문서의 핵심 내용을 요약해줘", "중요한 규칙을 알려줘", "처음 읽는 사람이 알아야 할 것은?"];

/** Turn "[1]" citations into links so they can be clicked to open the source. */
function linkCitations(text: string) {
  return text.replace(/\[(\d+)\](?!\()/g, "[\\[$1\\]](#source-$1)");
}

function fromStored(m: StoredMessage): Message {
  return { id: String(m.id), role: m.role, content: m.content, sources: m.sources ?? [], grounded: m.grounded };
}

export default function Chat({
  conversationId,
  documentIds,
  onConversationStarted,
  onTurnComplete,
  onUnauthorized,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [activeSource, setActiveSource] = useState<Record<string, number | null>>({});
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // The conversation this component is currently showing. When the server creates a
  // conversation mid-stream we record it here first, so the prop change doesn't reload it.
  const shownIdRef = useRef<string | null>(conversationId);
  const isStreaming = messages.some((m) => m.streaming);

  useEffect(() => {
    if (conversationId === shownIdRef.current) return;
    shownIdRef.current = conversationId;
    abortRef.current?.abort();
    setActiveSource({});
    if (conversationId === null) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    getConversation(conversationId)
      .then((c) => !cancelled && setMessages(c.messages.map(fromStored)))
      .catch((e) => {
        if (e instanceof UnauthorizedError) onUnauthorized();
        else if (!cancelled) setMessages([]);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [conversationId, onUnauthorized]);

  useEffect(() => {
    if (messages.length) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  function patch(id: string, update: (m: Message) => Partial<Message>) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...update(m) } : m)));
  }

  async function send(question: string) {
    question = question.trim();
    if (!question || isStreaming || loading) return;

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
        {
          question,
          conversation_id: shownIdRef.current,
          document_ids: documentIds.length ? documentIds : null,
        },
        controller.signal,
      );
      for await (const ev of stream) {
        switch (ev.event) {
          case "conversation":
            if (shownIdRef.current !== ev.data.id) {
              shownIdRef.current = ev.data.id;
              onConversationStarted(ev.data.id);
            }
            break;
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
      if (e instanceof UnauthorizedError) onUnauthorized();
      else if (!controller.signal.aborted) {
        patch(assistantId, () => ({ error: (e as Error).message || "서버에 연결할 수 없습니다." }));
      }
    } finally {
      patch(assistantId, () => ({ streaming: false }));
      if (abortRef.current === controller) abortRef.current = null;
      onTurnComplete();
    }
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-8 px-5 py-8 md:px-8">
          {loading && <p className="mt-10 animate-pulse text-sm text-fg-dim">대화를 불러오는 중…</p>}
          {!loading && messages.length === 0 && (
            <div className="animate-rise mt-6 flex flex-col gap-8 md:mt-20">
              <h1 className="text-4xl leading-[1.1] font-light tracking-[-0.03em] md:text-6xl">
                docsqa는 문서가
                <br />
                <strong className="font-bold">직접 대답하는</strong> 공간입니다.
              </h1>
              <p className="max-w-md text-lg font-light text-fg-dim">
                문서를 올리고 질문하세요. 모든 답변에는 근거가 된 원문이 함께 달립니다.
              </p>
              <div className="flex flex-wrap gap-2.5">
                {EXAMPLES.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => send(q)}
                    className="rounded-full border border-line px-5 py-2.5 text-sm transition-colors hover:border-blush hover:bg-blush hover:text-ink"
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
                {m.steps && <StepIndicator steps={m.steps} />}
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
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-[2rem] border border-line bg-field p-2 pl-6 transition-colors focus-within:border-fg">
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
            className="max-h-40 flex-1 resize-none self-center bg-transparent py-2 text-base font-light outline-none placeholder:text-fg-dim"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="flex h-12 items-center gap-2 rounded-full bg-ink px-5 font-bold text-cream"
            >
              <span className="size-2.5 rounded-sm bg-cream" />
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
