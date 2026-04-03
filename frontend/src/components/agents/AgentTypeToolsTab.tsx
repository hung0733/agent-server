import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchAgentTools, updateAgentTypeTool } from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { AgentToolsPayload } from "../../types/dashboard";

const emptyPayload: AgentToolsPayload = {
  agents: [],
  agentTypes: [],
  availableTools: [],
  source: "empty",
};

function updateLocalAgentTypeToolState(
  current: AgentToolsPayload,
  agentTypeId: string,
  toolId: string,
  isActive: boolean,
): AgentToolsPayload {
  return {
    ...current,
    agentTypes: current.agentTypes.map((agentType) => {
      if (agentType.id !== agentTypeId) return agentType;
      return {
        ...agentType,
        tools: agentType.tools.map((tool) =>
          tool.id === toolId
            ? {
                ...tool,
                isEnabled: isActive,
                source: isActive ? "type" : "inactive",
              }
            : tool,
        ),
      };
    }),
  };
}

export default function AgentTypeToolsTab() {
  const { t } = useTranslation();
  const { isLoading, resource } = useDashboardResource(fetchAgentTools, emptyPayload, {
    blockOnFirstLoad: true,
  });
  const [payload, setPayload] = useState<AgentToolsPayload>(emptyPayload);
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState<string>("");

  useEffect(() => {
    console.log('[AgentTypeToolsTab] resource received:', resource);
    console.log('[AgentTypeToolsTab] agentTypes count:', resource.agentTypes?.length || 0);
    setPayload(resource);
    setSelectedAgentTypeId((current) => {
      if (resource.agentTypes.some((agentType) => agentType.id === current)) {
        return current;
      }
      return resource.agentTypes[0]?.id ?? "";
    });
  }, [resource]);

  const availableToolNames = useMemo(
    () => payload.availableTools.map((tool) => tool.name).join(", "),
    [payload.availableTools],
  );

  const selectedAgentType = payload.agentTypes.find((agentType) => agentType.id === selectedAgentTypeId) ?? payload.agentTypes[0];

  async function handleAgentTypeToolToggle(agentTypeId: string, toolId: string, isActive: boolean) {
    const response = await updateAgentTypeTool(agentTypeId, toolId, { isActive });
    setPayload((current) => updateLocalAgentTypeToolState(current, agentTypeId, toolId, response.tool.isActive));
  }

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入員工類型工具...</section>;
  }

  if (payload.agentTypes.length === 0) {
    return (
      <section className="card agents-placeholder">
        <h3>{t("agents.agentTypeTools.title")}</h3>
        <p>尚未建立員工類型。請先在「員工類型」Tab 建立員工類型。</p>
      </section>
    );
  }

  return (
    <section className="agent-tools">
      <div className="agent-tools__header">
        <h3>{t("agents.agentTypeTools.title")}</h3>
      </div>

      <div className="agent-tools__layout">
        <aside className="card agent-tools__navigator">
          <h4>{t("agents.agentTypeTools.agentTypeSelector")}</h4>
          <div className="agent-tools__agent-list">
            {payload.agentTypes.map((agentType) => (
              <button
                key={agentType.id}
                type="button"
                aria-label={agentType.name}
                className={`agent-tools__agent-chip${selectedAgentType?.id === agentType.id ? " is-active" : ""}`}
                onClick={() => setSelectedAgentTypeId(agentType.id)}
              >
                <span>{agentType.name}</span>
                <small>{agentType.role}</small>
              </button>
            ))}
          </div>
        </aside>

        {selectedAgentType ? (
          <article className="card agent-tools__agent-detail">
            <header className="agent-tools__agent-header">
              <div>
                <h4>{selectedAgentType.name}</h4>
                <p>{selectedAgentType.role}</p>
              </div>
            </header>

            <ul className="agent-tools__list">
              {selectedAgentType.tools.map((tool) => (
                <li key={tool.id} className="agent-tools__item">
                  <label>
                    <input
                      type="checkbox"
                      checked={tool.isEnabled}
                      disabled={!tool.isActive}
                      onChange={(event) => void handleAgentTypeToolToggle(selectedAgentType.id, tool.id, event.target.checked)}
                    />
                    <span>{tool.name}</span>
                  </label>
                  <small>{tool.description}</small>
                  <small>{t(`agents.agentTypeTools.source.${tool.source}`)}</small>
                </li>
              ))}
            </ul>
          </article>
        ) : null}
      </div>
    </section>
  );
}
