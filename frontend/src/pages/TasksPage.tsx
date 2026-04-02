import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { fetchTasks } from "../api/dashboard";
import TaskTimeline from "../components/tasks/TaskTimeline";
import SectionHeader from "../components/ui/SectionHeader";
import type { TimelineItem } from "../types/dashboard";

export default function TasksPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const observerRef = useRef<IntersectionObserver | null>(null);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchTasks();
      setItems(payload.items);
      setHasMore(payload.hasMore);
      setNextCursor(payload.nextCursor);
    } catch (err) {
      setError(t("tasks.errorLoading"));
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore || !hasMore) return;

    setIsLoadingMore(true);
    setError(null);
    try {
      const payload = await fetchTasks(nextCursor);
      setItems((prev) => [...prev, ...payload.items]);
      setHasMore(payload.hasMore);
      setNextCursor(payload.nextCursor);
    } catch (err) {
      setError(t("tasks.errorLoadingMore"));
      console.error(err);
    } finally {
      setIsLoadingMore(false);
    }
  }, [nextCursor, isLoadingMore, hasMore]);

  useEffect(() => {
    if (!hasMore || isLoadingMore) return;

    const options = {
      root: null,
      rootMargin: "100px",
      threshold: 0,
    };

    observerRef.current = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && !isLoadingMore && nextCursor) {
        loadMore();
      }
    }, options);

    if (loadMoreRef.current) {
      observerRef.current.observe(loadMoreRef.current);
    }

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [hasMore, isLoadingMore, nextCursor, loadMore]);

  if (isLoading && items.length === 0) {
    return <section className="card dashboard-loading">{t("tasks.loading")}</section>;
  }

  if (error && items.length === 0) {
    return (
      <section>
        <SectionHeader title={t("tasks.title")} subtitle={t("tasks.subtitle")} />
        <div className="card error-indicator">{error}</div>
      </section>
    );
  }

  return (
    <section>
      <SectionHeader title={t("tasks.title")} subtitle={t("tasks.subtitle")} />
      <TaskTimeline items={items} />
      <div ref={loadMoreRef} style={{ height: "1px" }} />
      {isLoadingMore && <div className="card loading-more-indicator">{t("tasks.loadingMore")}</div>}
      {!hasMore && !isLoadingMore && items.length > 0 && (
        <div className="card no-more-indicator">{t("tasks.noMore")}</div>
      )}
      {error && items.length > 0 && <div className="card error-indicator">{error}</div>}
    </section>
  );
}