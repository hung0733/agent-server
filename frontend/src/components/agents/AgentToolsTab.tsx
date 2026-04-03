import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchAgentTools, updateAgentTool } from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { AgentToolsPayload } from "../../types/dashboard";

const emptyPayload: AgentToolsPayload = {
  agents: [],
  agentTypes: [],
  availableTools: [],
  source: "empty",
};

function updateLocalAgentToolState(
  current: AgentToolsPayload,
  agentId: string,
  toolId: string,
  isEnabled: boolean,
): AgentToolsPayload {
  return {
    ...current,
    agents: current.agents.map((agent) => {
      if (agent.id !== agentId) return agent;
      return {
        ...agent,
        tools: agent.tools.map((tool) =>
          tool.id === toolId
            ? {
                ...tool,
                isEnabled,
                source: "override",
              }
            : tool,
        ),
      };
    }),
  };
}

export default function AgentToolsTab() {
  const { t } = useTranslation();
  const { isLoading, resource } = useDashboardResource(fetchAgentTools, emptyPayload, {
    blockOnFirstLoad: true,
  });
  const [payload, setPayload] = useState<AgentToolsPayload>(emptyPayload);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");

  useEffect(() => {
    setPayload(resource);
    setSelectedAgentId((current) => {
      if (resource.agents.some((agent) => agent.id === current)) {
        return current;
      }
      return resource.agents[0]?.id ?? "";
    });
  }, [resource]);

  const availableToolNames = useMemo(
    () => payload.availableTools.map((tool) => tool.name).join(", "),
    [payload.availableTools],
  );

  const selectedAgent = payload.agents.find((agent) => agent.id === selectedAgentId) ?? payload.agents[0];

  async function handleAgentToolToggle(agentId: string, toolId: string, isEnabled: boolean) {
    const response = await updateAgentTool(agentId, toolId, { isEnabled });
    setPayload((current) => updateLocalAgentToolState(current, agentId, toolId, response.tool.isEnabled));
  }

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入員工工具...</section>;
  }

  if (payload.agents.length === 0) {
    return (
      <section className="card agents-placeholder">
        <h3>{t("agents.agentTools.title")}</h3>
        <p>尚未建立員工。請先在「員工」Tab 建立員工。</p>
      </section>
    );
  }

  return (
    <section className="agent-tools">
      <div className="agent-tools__header">
        <h3>{t("agents.agentTools.title")}</h3>
      </div>

      <div className="agent-tools__layout">
        <aside className="card agent-tools__navigator">
          <h4>{t("agents.agentTools.agentSelector")}</h4>
          <div className="agent-tools__agent-list">
            {payload.agents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                aria-label={agent.name}
                className={`agent-tools__agent-chip${selectedAgent?.id === agent.id ? " is-active" : ""}`}
                onClick={() => setSelectedAgentId(agent.id)}
              >
                <span>{agent.name}</span>
                <small>{agent.role}</small>
              </button>
            ))}
          </div>
        </aside>

        {selectedAgent ? (
          <article className="card agent-tools__agent-detail">
            <header className="agent-tools__agent-header">
              <div>
                <h4>{selectedAgent.name}</h4>
                <p>{selectedAgent.role}</p>
              </div>
            </header>

            <ul className="agent-tools__list">
              {selectedAgent.tools.map((tool) => (
                <li key={tool.id} className="agent-tools__item">
                  <label>
                    <input
                      type="checkbox"
                      checked={tool.isEnabled}
                      disabled={!tool.isActive}
                      onChange={(event) => void handleAgentToolToggle(selectedAgent.id, tool.id, event.target.checked)}
                    />
                    <span>{tool.name}</span>
                  </label>
                  <small>{tool.description}</small>
                  <small>{t(`agents.agentTools.source.${tool.source}`)}</small>
                </li>
              ))}
            </ul>
          </article>
        ) : null}
      </div>
    </section>
  );
}
