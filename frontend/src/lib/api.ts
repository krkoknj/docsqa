export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DocumentInfo = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  chunk_count: number;
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

export type GraphNode = "retrieve" | "grade" | "rewrite" | "generate" | "check";

export type StepEvent = { node: GraphNode; status: "start" | "end"; detail: string | null };

export type ChatEvent =
  | { event: "step"; data: StepEvent }
  | { event: "sources"; data: Source[] }
  | { event: "reset"; data: Record<string, never> }
  | { event: "token"; data: { text: string } }
  | { event: "done"; data: { answer: string; grounded: boolean | null } }
  | { event: "error"; data: { message: string } };

export type HistoryMessage = { role: "user" | "assistant"; content: string };

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {}
  return `요청 실패 (${res.status})`;
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${API_URL}/api/documents`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/api/documents`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await errorMessage(res));
}

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
  body: { question: string; history: HistoryMessage[]; document_ids: string[] | null },
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
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
