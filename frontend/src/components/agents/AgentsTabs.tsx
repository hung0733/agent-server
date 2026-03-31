import { useTranslation } from "react-i18next";

type AgentTabKey = "agent" | "agent-type" | "schedule" | "tools";

interface AgentsTabsProps {
  activeTab: AgentTabKey;
  onChange: (tab: AgentTabKey) => void;
}

const tabs: Array<{ key: AgentTabKey; labelKey: string }> = [
  { key: "agent", labelKey: "agents.tabs.agent" },
  { key: "agent-type", labelKey: "agents.tabs.agentType" },
  { key: "schedule", labelKey: "agents.tabs.schedule" },
  { key: "tools", labelKey: "agents.tabs.tools" },
];

export type { AgentTabKey };

export default function AgentsTabs({ activeTab, onChange }: AgentsTabsProps) {
  const { t } = useTranslation();

  return (
    <div className="agents-tabs" role="tablist" aria-label={t("agents.tabs.label")}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className={`agents-tabs__tab${activeTab === tab.key ? " is-active" : ""}`}
          role="tab"
          aria-selected={activeTab === tab.key}
          onClick={() => onChange(tab.key)}
        >
          {t(tab.labelKey)}
        </button>
      ))}
    </div>
  );
}
