"use client";

import { useEffect, useRef, useState } from "react";
import { useNav, useThreadList } from "@openuidev/react-ui";
import { MessageSquare, Search } from "lucide-react";

import { ToolPage } from "@/components/tools/shared";

function when(createdAt: string | number) {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function SearchPage() {
  const threads = useThreadList((s) => s.threads);
  const selectThread = useThreadList((s) => s.selectThread);
  const hasMore = useThreadList((s) => s.hasMoreThreads);
  const loadMore = useThreadList((s) => s.loadMoreThreads);
  const { navigate } = useNav();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => inputRef.current?.focus(), []);

  const needle = query.trim().toLowerCase();
  const results = threads.filter((t) => !needle || (t.title ?? "").toLowerCase().includes(needle));

  const open = (id: string) => {
    navigate(undefined);
    selectThread(id);
  };

  return (
    <ToolPage icon={<Search size={13} />} eyebrow="Search" title="Find a conversation">
      <label className="qc-search qc-search--large">
        <Search size={17} />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search your chats by title…"
          onKeyDown={(e) => {
            if (e.key === "Enter" && results[0]) open(results[0].id);
          }}
        />
        <span className="qc-pill">{results.length}</span>
      </label>
      <ul className="qc-results">
        {results.map((thread) => (
          <li key={thread.id}>
            <button type="button" onClick={() => open(thread.id)}>
              <MessageSquare size={15} />
              <span className="qc-results__title">{thread.title || "Untitled chat"}</span>
              <span className="qc-results__date">{when(thread.createdAt)}</span>
            </button>
          </li>
        ))}
        {results.length === 0 && <li className="qc-state">No chats match “{query}”.</li>}
      </ul>
      {hasMore && (
        <button type="button" className="qc-ghost-button" onClick={loadMore}>
          Load older chats
        </button>
      )}
    </ToolPage>
  );
}
