import { useTranslation } from "react-i18next";
import { fetchMemory } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import StatCard from "../components/ui/StatCard";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { memoryPayload } from "../mock/dashboard";

export default function MemoryPage() {
  const { t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchMemory, memoryPayload, {
    blockOnFirstLoad: true,
  });
  const emptyTitle = t("memory.emptyTitle");
  const emptyBody = t("memory.emptyBody");

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
      <section className="card">
        <h3>{payload.summary.title}</h3>
        <p>{payload.summary.body}</p>
      </section>

      <section className="overview-kpis">
        {payload.stats.length > 0 ? (
          payload.stats.map((stat) => (
            <StatCard
              key={`${stat.title}-${stat.note}`}
              title={stat.title}
              value={stat.value}
              note={stat.note}
              status={stat.status}
            />
          ))
        ) : (
          <EmptyState title={emptyTitle} body={emptyBody} />
        )}
      </section>

      <section className="timeline">
        {payload.recentEntries.length > 0 ? (
          payload.recentEntries.map((entry) => (
            <article key={entry.id} className="card timeline-item">
              <div className="timeline-item__header">
                <h3>{entry.title}</h3>
                <p>{entry.timestamp}</p>
              </div>
              <p className="timeline-item__summary">{entry.detail}</p>
            </article>
          ))
        ) : (
          <EmptyState title={emptyTitle} body={emptyBody} />
        )}
      </section>
    </section>
  );
}
