import { useTranslation } from "react-i18next";
import { fetchAgents } from "../api/dashboard";
import AgentCard from "../components/agents/AgentCard";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { agentsPayload } from "../mock/dashboard";

export default function AgentsPage() {
  const { t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchAgents, agentsPayload, {
    blockOnFirstLoad: true,
  });

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("agents.title")} subtitle={t("agents.subtitle")} />
      <div className="agent-grid">
        {payload.agents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} />
        ))}
      </div>
    </section>
  );
}
