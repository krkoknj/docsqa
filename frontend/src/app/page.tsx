"use client";

import { useCallback, useEffect, useState } from "react";
import AuthScreen from "@/components/AuthScreen";
import Chat from "@/components/Chat";
import ConversationList from "@/components/ConversationList";
import DocumentPanel from "@/components/DocumentPanel";
import SegmentedTabs from "@/components/SegmentedTabs";
import {
  getMe,
  isIndexing,
  listConversations,
  listDocuments,
  logout,
  UnauthorizedError,
  type Conversation,
  type DocumentInfo,
  type User,
} from "@/lib/api";

type Tab = "conversations" | "documents";
const POLL_MS = 1500;

export default function Home() {
  // undefined = still checking the session
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  if (user === undefined) {
    return <main className="grid h-full place-items-center text-sm text-fg-dim">불러오는 중…</main>;
  }
  if (user === null) return <AuthScreen onAuthenticated={setUser} />;
  return <Workspace key={user.id} user={user} onSignedOut={() => setUser(null)} />;
}

function Workspace({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const [tab, setTab] = useState<Tab>("conversations");
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState<string | null>(null);

  const handleError = useCallback(
    (e: unknown) => {
      if (e instanceof UnauthorizedError) onSignedOut();
      else setLoadError("백엔드 서버에 연결할 수 없습니다. API 서버가 실행 중인지 확인하세요.");
    },
    [onSignedOut],
  );

  const refreshDocuments = useCallback(async () => {
    try {
      const docs = await listDocuments();
      setDocuments(docs);
      setSelectedIds(
        (prev) => new Set([...prev].filter((id) => docs.some((d) => d.id === id && d.status === "ready"))),
      );
      setLoadError(null);
    } catch (e) {
      handleError(e);
    }
  }, [handleError]);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch (e) {
      handleError(e);
    }
  }, [handleError]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch from an external API
    refreshDocuments();
    refreshConversations();
  }, [refreshDocuments, refreshConversations]);

  // Poll while the indexing worker still has documents in flight.
  const indexing = documents.some(isIndexing);
  useEffect(() => {
    if (!indexing) return;
    const timer = setInterval(refreshDocuments, POLL_MS);
    return () => clearInterval(timer);
  }, [indexing, refreshDocuments]);

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function signOut() {
    await logout().catch(() => {});
    onSignedOut();
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "conversations", label: `대화 ${conversations.length}` },
    { id: "documents", label: `문서 ${documents.length}${indexing ? " · 색인 중" : ""}` },
  ];

  return (
    <main className="flex h-full flex-col md:flex-row">
      <aside className="flex w-full flex-col gap-5 p-5 md:h-full md:w-[22rem] md:p-7">
        <header className="flex items-start justify-between gap-3">
          <div>
            <p className="text-5xl leading-none font-bold tracking-[-0.04em]">docsqa</p>
            <p className="mt-3 truncate text-sm font-light text-fg-dim" title={user.email}>
              {user.email}
            </p>
          </div>
          <button
            type="button"
            onClick={signOut}
            className="shrink-0 rounded-full border border-line px-3 py-1.5 text-xs font-bold hover:border-fg"
          >
            로그아웃
          </button>
        </header>

        <SegmentedTabs options={tabs} value={tab} onChange={setTab} label="사이드바" className="bg-panel" />

        {tab === "conversations" ? (
          <ConversationList
            conversations={conversations}
            activeId={conversationId}
            onSelect={setConversationId}
            onChange={refreshConversations}
          />
        ) : (
          <DocumentPanel
            documents={documents}
            selectedIds={selectedIds}
            onToggle={toggle}
            onChange={refreshDocuments}
          />
        )}
      </aside>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-panel md:my-3 md:mr-3 md:rounded-[2.5rem]">
        {loadError && <p className="bg-mustard px-6 py-3 text-sm font-bold text-ink">{loadError}</p>}
        {documents.length > 0 && !documents.some((d) => d.status === "ready") && (
          <p className="bg-page px-6 py-3 text-sm text-fg-dim">
            {indexing ? "문서를 색인하고 있어요. 끝나면 질문할 수 있습니다." : "검색할 수 있는 문서가 없어요."}
          </p>
        )}
        <Chat
          conversationId={conversationId}
          documentIds={[...selectedIds]}
          onConversationStarted={setConversationId}
          onTurnComplete={refreshConversations}
          onUnauthorized={onSignedOut}
        />
      </div>
    </main>
  );
}
