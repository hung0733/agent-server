import { useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAgents } from "../api/dashboard";
import AgentCard from "../components/agents/AgentCard";
import AgentToolsTab from "../components/agents/AgentToolsTab";
import AgentTypesTab from "../components/agents/AgentTypesTab";
import AgentsTabs, { type AgentTabKey } from "../components/agents/AgentsTabs";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { agentsPayload } from "../mock/dashboard";

export default function AgentsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<AgentTabKey>("agent");
  const { isLoading, resource: payload } = useDashboardResource(fetchAgents, agentsPayload, {
    blockOnFirstLoad: true,
  });

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("agents.title")} subtitle={t("agents.subtitle")} />
      <AgentsTabs activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "agent" ? (
        <div className="agent-grid">
          {payload.agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      ) : null}

      {activeTab === "agent-type" ? <AgentTypesTab /> : null}

      {activeTab === "schedule" ? (
        <article className="card agents-placeholder">
          <h3>{t("agents.tabs.schedule")}</h3>
          <p>{t("agents.tabs.placeholder")}</p>
        </article>
      ) : null}

      {activeTab === "tools" ? <AgentToolsTab /> : null}
    </section>
  );
}
