/**
 * Backend client. Requests go to same-origin `/api/*`, which Next.js proxies to the
 * FastAPI backend (see next.config.ts), so the httpOnly session cookie just works.
 */

export type User = { id: string; email: string; created_at: string };

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export type DocumentInfo = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  chunk_count: number;
  status: DocumentStatus;
  error: string | null;
  created_at: string;
};

export type Source = {
  id: number;
  document_id: string;
  source: string;
  page: number | null;
  /** Final ranking score (reranker score if reranked), higher is better. */
  score: number;
  vector_rank: number | null;
  keyword_rank: number | null;
  rerank_score: number | null;
  content: string;
  /** Set by the relevance grader; undefined until grading finishes. */
  relevant?: boolean;
};

export type Conversation = { id: string; title: string; created_at: string; updated_at: string };

export type StoredMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[] | null;
  grounded: boolean | null;
  created_at: string;
};

export type GraphNode = "retrieve" | "grade" | "rewrite" | "generate" | "check";

export type StepEvent = { node: GraphNode; status: "start" | "end"; detail: string | null };

export type ChatEvent =
  | { event: "conversation"; data: { id: string; title: string } }
  | { event: "step"; data: StepEvent }
  | { event: "sources"; data: Source[] }
  | { event: "reset"; data: Record<string, never> }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: { answer: string; grounded: boolean | null } }
  | { event: "error"; data: { message: string } };

/** Thrown on 401 so the app can drop back to the login screen. */
export class UnauthorizedError extends Error {}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return "입력값을 확인해 주세요.";
  } catch {}
  return `요청 실패 (${res.status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (res.status === 401) throw new UnauthorizedError(await errorMessage(res));
  if (!res.ok) throw new Error(await errorMessage(res));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// --- auth ---------------------------------------------------------------------------

export const getMe = () => request<User>("/api/auth/me");
export const login = (email: string, password: string) => request<User>("/api/auth/login", json({ email, password }));
export const signup = (email: string, password: string) =>
  request<User>("/api/auth/signup", json({ email, password }));
export const logout = () => request<void>("/api/auth/logout", { method: "POST" });

// --- documents -----------------------------------------------------------------------

export const listDocuments = () => request<DocumentInfo[]>("/api/documents");

export function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<DocumentInfo>("/api/documents", { method: "POST", body: form });
}

export const retryDocument = (id: string) => request<DocumentInfo>(`/api/documents/${id}/retry`, { method: "POST" });
export const deleteDocument = (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" });

// --- conversations -------------------------------------------------------------------

export const listConversations = () => request<Conversation[]>("/api/conversations");
export const getConversation = (id: string) =>
  request<Conversation & { messages: StoredMessage[] }>(`/api/conversations/${id}`);
export const deleteConversation = (id: string) => request<void>(`/api/conversations/${id}`, { method: "DELETE" });

// --- chat stream ---------------------------------------------------------------------

/** Parse one SSE block ("event: x\r\ndata: {...}") into a typed event. */
function parseBlock(block: string): ChatEvent | null {
  let event = "";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!event || data.length === 0) return null;
  return { event, data: JSON.parse(data.join("\n")) } as ChatEvent;
}

/**
 * POST a question and yield SSE events as they arrive.
 * EventSource only supports GET, so the stream is read manually.
 */
export async function* streamChat(
  body: { question: string; conversation_id: string | null; document_ids: string[] | null },
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch("/api/chat", { ...json(body), signal });
  if (res.status === 401) throw new UnauthorizedError(await errorMessage(res));
  if (!res.ok || !res.body) throw new Error(await errorMessage(res));

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const parsed = parseBlock(block);
      if (parsed) yield parsed;
    }
  }
}
