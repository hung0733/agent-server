import { useTranslation } from "react-i18next";
import Badge from "../ui/Badge";
import { OverviewSummary } from "../../types/dashboard";

export default function OverviewHero({ summary }: { summary: OverviewSummary }) {
  const { t } = useTranslation();

  return (
    <section className="card overview-hero">
      <div>
        <p className="overview-hero__eyebrow">{t("overview.title")}</p>
        <h2 className="overview-hero__title">{summary.headline}</h2>
        <p className="overview-hero__text">{summary.conclusion}</p>
      </div>
      <div className="overview-hero__score-wrap">
        <div className="overview-hero__score">
          <span className="overview-hero__score-value">{summary.score}</span>
          <span className="overview-hero__score-label">{t("overview.score")}</span>
        </div>
        <Badge tone={summary.status === "idle" ? "warning" : summary.status} label={summary.status === "healthy" ? "穩定運行" : summary.status === "warning" ? "需要留意" : "需要介入"} />
      </div>
    </section>
  );
}
