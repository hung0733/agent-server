import { useState } from "react";
import { useTranslation } from "react-i18next";
import AgentTab from "../components/agents/AgentTab";
import AgentToolsTab from "../components/agents/AgentToolsTab";
import AgentTypeToolsTab from "../components/agents/AgentTypeToolsTab";
import AgentTypesTab from "../components/agents/AgentTypesTab";
import AgentsTabs, { type AgentTabKey } from "../components/agents/AgentsTabs";
import SectionHeader from "../components/ui/SectionHeader";

export default function AgentsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<AgentTabKey>("agent");

  return (
    <section>
      <SectionHeader title={t("agents.title")} subtitle={t("agents.subtitle")} />
      <AgentsTabs activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "agent" ? <AgentTab /> : null}

      {activeTab === "agent-type" ? <AgentTypesTab /> : null}

      {activeTab === "schedule" ? (
        <article className="card agents-placeholder">
          <h3>{t("agents.tabs.schedule")}</h3>
          <p>{t("agents.tabs.placeholder")}</p>
        </article>
      ) : null}

      {activeTab === "agent-tools" ? <AgentToolsTab /> : null}

      {activeTab === "agent-type-tools" ? <AgentTypeToolsTab /> : null}
    </section>
  );
}
