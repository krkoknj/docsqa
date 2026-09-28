"use client";

import { useCallback, useEffect, useState } from "react";
import Chat from "@/components/Chat";
import DocumentPanel from "@/components/DocumentPanel";
import { listDocuments, type DocumentInfo } from "@/lib/api";

export default function Home() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const docs = await listDocuments();
      setDocuments(docs);
      setSelectedIds((prev) => new Set([...prev].filter((id) => docs.some((d) => d.id === id))));
      setLoadError(null);
    } catch {
      setLoadError("백엔드 서버에 연결할 수 없습니다. API 서버가 실행 중인지 확인하세요.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch from an external API
    refresh();
  }, [refresh]);

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <main className="flex h-full flex-col md:flex-row">
      <DocumentPanel documents={documents} selectedIds={selectedIds} onToggle={toggle} onChange={refresh} />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-ink-soft md:my-3 md:mr-3 md:rounded-[2.5rem]">
        {loadError && <p className="bg-mustard px-6 py-3 text-sm font-bold text-ink">{loadError}</p>}
        <Chat documentIds={[...selectedIds]} />
      </div>
    </main>
  );
}
