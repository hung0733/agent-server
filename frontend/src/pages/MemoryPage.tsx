import { useTranslation } from "react-i18next";
import { fetchMemory } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import StatCard from "../components/ui/StatCard";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { MemoryPayload } from "../types/dashboard";

const emptyMemoryPayload: MemoryPayload = {
  stats: {
    agents: 0,
    tasks: 0,
    messages: 0,
  },
  health: {
    status: "idle",
    summary: "",
  },
  recentEntries: [],
  source: "empty",
};

function formatDateTime(value: string, locale: string): string {
  const timestamp = new Date(value);

  if (Number.isNaN(timestamp.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(timestamp);
}

export default function MemoryPage() {
  const { i18n, t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchMemory, emptyMemoryPayload, {
    blockOnFirstLoad: true,
  });
  const emptyTitle = t("memory.emptyTitle");
  const emptyBody = t("memory.emptyBody");
  const hasActivity = payload.stats.tasks > 0 || payload.stats.messages > 0 || payload.recentEntries.length > 0;
  const stats = [
    {
      title: t("memory.stats.agents"),
      value: payload.stats.agents,
      note: t("memory.stats.agentsNote"),
    },
    {
      title: t("memory.stats.tasks"),
      value: payload.stats.tasks,
      note: t("memory.stats.tasksNote"),
    },
    {
      title: t("memory.stats.messages"),
      value: payload.stats.messages,
      note: t("memory.stats.messagesNote"),
    },
  ];

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  if (!hasActivity) {
    return (
      <section>
        <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
        <EmptyState title={emptyTitle} body={emptyBody} />
      </section>
    );
  }

  return (
    <section>
      <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
      <section className="card">
        <h3>{t(`common.status.${payload.health.status}`)}</h3>
        <p>{payload.health.summary}</p>
      </section>

      <section className="overview-kpis">
        {stats.map((stat) => (
          <StatCard
            key={stat.title}
            title={stat.title}
            value={stat.value}
            note={stat.note}
            status={payload.health.status === "idle" ? "healthy" : payload.health.status}
          />
        ))}
      </section>

      <section className="timeline">
        {payload.recentEntries.map((entry) => (
          <article
            key={`${entry.kind}-${entry.agent}-${entry.timestamp}`}
            className="card timeline-item"
          >
            <div className="timeline-item__header">
              <div>
                <h3>{entry.agent}</h3>
                <p>{t(`memory.entry.${entry.kind}`)}</p>
              </div>
              <p>{formatDateTime(entry.timestamp, i18n.language)}</p>
            </div>
            <p className="timeline-item__summary">{entry.summary}</p>
          </article>
        ))}
      </section>
    </section>
  );
}
