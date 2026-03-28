import { useTranslation } from "react-i18next";
import { fetchOverview } from "../api/dashboard";
import InterventionPanel from "../components/overview/InterventionPanel";
import OverviewHero from "../components/overview/OverviewHero";
import StatCard from "../components/ui/StatCard";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { overviewPayload } from "../mock/dashboard";

export default function OverviewPage() {
  const { t } = useTranslation();
  const overview = useDashboardResource(fetchOverview, overviewPayload);
  const statLabelMap = {
    "待審批": t("stats.pendingReview"),
    "運行異常": t("stats.anomalies"),
    "停滯任務": t("stats.stalled"),
    "預算風險": t("stats.budgetRisk"),
  };

  return (
    <section className="overview-grid">
      <OverviewHero summary={overview.summary} />
      <div className="overview-kpis">
        {overview.stats.map((item) => (
          <StatCard
            key={item.label}
            title={statLabelMap[item.label as keyof typeof statLabelMap] ?? item.label}
            value={item.value}
            note={item.note}
            status={item.status === "idle" ? "warning" : item.status}
          />
        ))}
      </div>
      <InterventionPanel overview={overview} />
    </section>
  );
}
