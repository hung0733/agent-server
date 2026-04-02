import { useTranslation } from "react-i18next";
import { useState, useEffect, useRef } from "react";
import { fetchSTM, fetchLTM } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import { STMEntry, LTMEntry } from "../types/dashboard";
import { formatServerTimestamp } from "../utils/format";

type MemoryEntry = STMEntry | LTMEntry;

function useMemoryEntries() {
  const [stmEntries, setStmEntries] = useState<STMEntry[]>([]);
  const [ltmEntries, setLtmEntries] = useState<LTMEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  useEffect(() => {
    async function loadInitial() {
      setIsLoading(true);
      try {
        const stmPayload = await fetchSTM();
        const ltmPayload = await fetchLTM();
        
        setStmEntries(stmPayload.entries);
        setLtmEntries(ltmPayload.entries);
        setHasMore(ltmPayload.hasMore);
        setNextCursor(ltmPayload.nextCursor);
      } catch (error) {
        console.error("Failed to load memory entries:", error);
      } finally {
        setIsLoading(false);
      }
    }
    loadInitial();
  }, []);

  async function loadMore() {
    if (!hasMore || isLoadingMore || !nextCursor) return;

    setIsLoadingMore(true);
    try {
      const ltmPayload = await fetchLTM(nextCursor);
      
      setLtmEntries(prev => [...prev, ...ltmPayload.entries]);
      setHasMore(ltmPayload.hasMore);
      setNextCursor(ltmPayload.nextCursor);
    } catch (error) {
      console.error("Failed to load more LTM entries:", error);
    } finally {
      setIsLoadingMore(false);
    }
  }

  const mergedEntries = [...stmEntries, ...ltmEntries]
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));

  return {
    entries: mergedEntries,
    isLoading,
    isLoadingMore,
    hasMore,
    loadMore
  };
}

export default function MemoryPage() {
  const { t } = useTranslation();
  const { entries, isLoading, isLoadingMore, hasMore, loadMore } = useMemoryEntries();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!bottomRef.current || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMore();
        }
      },
      { threshold: 0.1 }
    );

    observer.observe(bottomRef.current);
    return () => observer.disconnect();
  }, [hasMore, loadMore]);

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  if (entries.length === 0) {
    return (
      <section>
        <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
        <EmptyState title={t("memory.emptyTitle")} body={t("memory.emptyBody")} />
      </section>
    );
  }

  return (
    <section>
      <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />

      <section className="timeline">
        {entries.map((entry) => (
          <article
            key={`${entry.kind}-${entry.id}`}
            className="card timeline-item"
          >
            <div className="timeline-item__header">
              <div>
                <h3>{entry.agent}</h3>
                <p>
                  {entry.kind === "stm" 
                    ? `STM - ${entry.sessionName}` 
                    : "LTM"}
                </p>
              </div>
              <p>{formatServerTimestamp(entry.timestamp)}</p>
            </div>
            <p className="timeline-item__summary">{entry.summary}</p>
          </article>
        ))}

        {hasMore && (
          <div ref={bottomRef} className="timeline-loader">
            {isLoadingMore ? "載入更多..." : "下拉載入更多"}
          </div>
        )}
      </section>
    </section>
  );
}