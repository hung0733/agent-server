import { useTranslation } from "react-i18next";
import { OverviewPayload } from "../../types/dashboard";

export default function InterventionPanel({ overview }: { overview: OverviewPayload }) {
  const { t } = useTranslation();

  return (
    <section className="card intervention-panel">
      <div>
        <p className="intervention-panel__label">{t("overview.interventionLabel")}</p>
        <h3>{overview.intervention.title || t("overview.interventionTitle")}</h3>
        <p className="intervention-panel__text">{overview.intervention.body || t("overview.interventionBody")}</p>
      </div>
      <ul className="intervention-panel__agents">
        {overview.activeAgents.map((agent) => (
          <li key={agent.id}>
            <strong>{agent.name}</strong>
            <span>{agent.role}</span>
          </li>
        ))}
      </ul>
      <div className="intervention-panel__summary card">
        <div>
          <p className="intervention-panel__label">{t("overview.usageSummary")}</p>
          <strong>{overview.railSummary.usageText}</strong>
        </div>
        <div>
          <p className="intervention-panel__label">{t("overview.activeAgents")}</p>
          <strong>{overview.activeAgents.length}</strong>
        </div>
      </div>
    </section>
  );
}
