import { useTranslation } from "react-i18next";
import { AgentCardData } from "../../types/dashboard";
import Badge from "../ui/Badge";

const toneMap = {
  healthy: "healthy",
  warning: "warning",
  danger: "danger",
  idle: "warning",
} as const;

const labelMap = {
  healthy: "工作中",
  warning: "待留意",
  danger: "需處理",
  idle: "待命",
};

export default function AgentCard({ agent }: { agent: AgentCardData }) {
  const { t } = useTranslation();

  return (
    <article className="card agent-card">
      <header className="agent-card__header">
        <div>
          <h3>{agent.name}</h3>
          <p>{agent.role}</p>
        </div>
        <Badge tone={toneMap[agent.status]} label={labelMap[agent.status]} />
      </header>
      <dl className="agent-card__grid">
        <div>
          <dt>{t("agents.currentStatus")}</dt>
          <dd>{agent.status === "healthy" ? t("common.badge.working") : labelMap[agent.status]}</dd>
        </div>
        <div>
          <dt>{t("agents.currentTask")}</dt>
          <dd>{agent.currentTask}</dd>
        </div>
        <div>
          <dt>{t("agents.latestOutput")}</dt>
          <dd>{agent.latestOutput}</dd>
        </div>
        <div>
          <dt>{t("agents.scheduled")}</dt>
          <dd>{agent.scheduled ? t("agents.scheduledYes") : t("agents.scheduledNo")}</dd>
        </div>
      </dl>
    </article>
  );
}
