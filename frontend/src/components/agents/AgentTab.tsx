import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  createAgent,
  fetchAgentMemoryBlocks,
  fetchAgents,
  fetchAgentTypes,
  fetchSettings,
  updateAgent,
} from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { agentTypesPayload } from "../../mock/dashboard";
import type {
  AgentCardData,
  AgentTypeItem,
  AgentsPayload,
  SettingsPayload,
} from "../../types/dashboard";

const EMPTY_AGENTS_PAYLOAD: AgentsPayload = { agents: [], source: "mock" };

interface FormState {
  name: string;
  agentTypeId: string;
  phoneNo: string;
  whatsappKey: string;
  isActive: boolean;
  isSubAgent: boolean;
  endpointGroupId: string;
  soul: string;
  userProfile: string;
  identity: string;
}

const EMPTY_FORM: FormState = {
  name: "",
  agentTypeId: "",
  phoneNo: "",
  whatsappKey: "",
  isActive: true,
  isSubAgent: false,
  endpointGroupId: "",
  soul: "",
  userProfile: "",
  identity: "",
};

export default function AgentTab() {
  const { t } = useTranslation();
  const { isLoading, resource } = useDashboardResource(fetchAgents, EMPTY_AGENTS_PAYLOAD, {
    blockOnFirstLoad: true,
  });
  const { resource: typesResource } = useDashboardResource(
    fetchAgentTypes,
    agentTypesPayload,
    {},
  );

  const [items, setItems] = useState<AgentCardData[]>([]);
  const [agentTypes, setAgentTypes] = useState<AgentTypeItem[]>(agentTypesPayload.agentTypes);
  const [editing, setEditing] = useState<AgentCardData | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [memoryLoading, setMemoryLoading] = useState(false);

  const { resource: settingsResource } = useDashboardResource(
    fetchSettings,
    { locales: [], featureFlags: {}, endpoints: [], groups: [], authKeys: [], source: "mock" } as SettingsPayload,
    {},
  );
  const [endpointGroups, setEndpointGroups] = useState<SettingsPayload["groups"]>([]);

  useEffect(() => {
    setItems(resource.agents);
  }, [resource]);

  useEffect(() => {
    setAgentTypes(typesResource.agentTypes);
  }, [typesResource]);

  useEffect(() => {
    setEndpointGroups(settingsResource.groups);
  }, [settingsResource]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setShowForm(true);
  }

  function openEdit(item: AgentCardData) {
    setEditing(item);
    setForm({
      name: item.name,
      agentTypeId: item.agentTypeId ?? "",
      phoneNo: item.phoneNo ?? "",
      whatsappKey: item.whatsappKey ?? "",
      isActive: item.isActive,
      isSubAgent: item.isSubAgent,
      endpointGroupId: item.endpointGroupId ?? "",
      soul: "",
      userProfile: "",
      identity: "",
    });
    setFormError(null);
    setShowForm(true);
    setMemoryLoading(true);
    fetchAgentMemoryBlocks(item.id)
      .then((blocks) => {
        setForm((f) => ({
          ...f,
          soul: blocks.SOUL ?? "",
          userProfile: blocks.USER_PROFILE ?? "",
          identity: blocks.IDENTITY ?? "",
        }));
      })
      .catch(() => {
        // non-fatal — leave fields empty
      })
      .finally(() => {
        setMemoryLoading(false);
      });
  }

  function closeForm() {
    setShowForm(false);
    setEditing(null);
    setFormError(null);
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setFormError(t("agents.agent.errorNameRequired"));
      return;
    }
    if (!form.agentTypeId) {
      setFormError(t("agents.agent.errorTypeRequired"));
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        const result = await updateAgent(editing.id, {
          name: form.name.trim(),
          agentTypeId: form.agentTypeId,
          phoneNo: form.phoneNo.trim() || undefined,
          whatsappKey: form.whatsappKey.trim() || undefined,
          isActive: form.isActive,
          isSubAgent: form.isSubAgent,
          endpointGroupId: form.endpointGroupId || undefined,
          memoryBlocks: {
            SOUL: form.soul || undefined,
            USER_PROFILE: form.userProfile || undefined,
            IDENTITY: form.identity || undefined,
          },
        });
        setItems((prev) => prev.map((i) => (i.id === editing.id ? result.agent : i)));
      } else {
        const result = await createAgent({
          name: form.name.trim(),
          agentTypeId: form.agentTypeId,
          phoneNo: form.phoneNo.trim() || undefined,
          whatsappKey: form.whatsappKey.trim() || undefined,
          isActive: form.isActive,
          isSubAgent: form.isSubAgent,
          endpointGroupId: form.endpointGroupId || undefined,
          memoryBlocks: {
            SOUL: form.soul || undefined,
            USER_PROFILE: form.userProfile || undefined,
            IDENTITY: form.identity || undefined,
          },
        });
        setItems((prev) => [...prev, result.agent]);
      }
      closeForm();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入...</section>;
  }

  return (
    <section className="agent-tab">
      <div className="agent-tab-header">
        <button className="btn btn-primary" onClick={openCreate}>
          {t("agents.agent.addButton")}
        </button>
      </div>

      {items.length === 0 ? (
        <p className="agent-tab-empty">{t("agents.agent.empty")}</p>
      ) : (
        <div className="agent-grid">
          {items.map((item) => (
            <article
              key={item.id}
              className={`card agent-card${!item.isActive ? " agent-card--inactive" : ""}`}
            >
              <header className="agent-card__header">
                <div>
                  <h3>{item.name}</h3>
                  <p>{item.agentTypeName ?? item.role ?? "—"}</p>
                </div>
                <div className="agent-card__badges">
                  {!item.isActive && (
                    <span className="badge badge--inactive">{t("agents.agent.badgeInactive")}</span>
                  )}
                  {item.isSubAgent && (
                    <span className="badge badge--sub">{t("agents.agent.badgeSub")}</span>
                  )}
                </div>
              </header>
              <dl className="agent-card__grid">
                <div>
                  <dt>{t("agents.currentTask")}</dt>
                  <dd>{item.currentTask || "—"}</dd>
                </div>
                <div>
                  <dt>{t("agents.latestOutput")}</dt>
                  <dd>{item.latestOutput || "—"}</dd>
                </div>
                <div>
                  <dt>{t("agents.scheduled")}</dt>
                  <dd>{item.scheduled ? t("agents.scheduledYes") : t("agents.scheduledNo")}</dd>
                </div>
              </dl>
              <div className="agent-card__actions">
                <button onClick={() => openEdit(item)}>{t("agents.agent.editAction")}</button>
              </div>
            </article>
          ))}
        </div>
      )}

      {showForm && (
        <div className="agent-tab-modal" onClick={closeForm}>
          <div
            role="dialog"
            aria-modal="true"
            className="agent-tab-modal-inner"
            onClick={(e) => e.stopPropagation()}
          >
            <h2>{editing ? t("agents.agent.editTitle") : t("agents.agent.createTitle")}</h2>

            <label>
              {t("agents.agent.nameLabel")}
              <input
                type="text"
                value={form.name}
                placeholder={t("agents.agent.namePlaceholder")}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </label>

            <label>
              {t("agents.agent.agentTypeLabel")}
              <select
                value={form.agentTypeId}
                onChange={(e) => setForm((f) => ({ ...f, agentTypeId: e.target.value }))}
              >
                <option value="">{t("agents.agent.agentTypeSelectPlaceholder")}</option>
                {agentTypes.map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              LLM Endpoint Group
              <select
                value={form.endpointGroupId}
                onChange={(e) => setForm((f) => ({ ...f, endpointGroupId: e.target.value }))}
              >
                <option value="">（不指定）</option>
                {endpointGroups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              {t("agents.agent.phoneNoLabel")}
              <input
                type="text"
                value={form.phoneNo}
                placeholder={t("agents.agent.phoneNoPlaceholder")}
                onChange={(e) => setForm((f) => ({ ...f, phoneNo: e.target.value }))}
              />
            </label>

            <label>
              {t("agents.agent.whatsappKeyLabel")}
              <input
                type="text"
                value={form.whatsappKey}
                placeholder={t("agents.agent.whatsappKeyPlaceholder")}
                onChange={(e) => setForm((f) => ({ ...f, whatsappKey: e.target.value }))}
              />
            </label>

            <fieldset style={{ border: "none", padding: 0, margin: "0.5rem 0" }}>
              <legend style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Memory Blocks</legend>

              <label>
                SOUL
                <textarea
                  rows={4}
                  value={form.soul}
                  disabled={memoryLoading}
                  placeholder={memoryLoading ? "載入中…" : "人格、價值觀、語氣偏好、行為準則"}
                  onChange={(e) => setForm((f) => ({ ...f, soul: e.target.value }))}
                />
              </label>

              <label>
                USER_PROFILE
                <textarea
                  rows={4}
                  value={form.userProfile}
                  disabled={memoryLoading}
                  placeholder={memoryLoading ? "載入中…" : "使用者偏好、背景、習慣、長期需求"}
                  onChange={(e) => setForm((f) => ({ ...f, userProfile: e.target.value }))}
                />
              </label>

              <label>
                IDENTITY
                <textarea
                  rows={4}
                  value={form.identity}
                  disabled={memoryLoading}
                  placeholder={memoryLoading ? "載入中…" : "Agent 身份標記"}
                  onChange={(e) => setForm((f) => ({ ...f, identity: e.target.value }))}
                />
              </label>
            </fieldset>

            <label>
              <input
                type="checkbox"
                checked={form.isActive}
                onChange={(e) => setForm((f) => ({ ...f, isActive: e.target.checked }))}
              />
              {t("agents.agent.isActiveLabel")}
            </label>

            <label>
              <input
                type="checkbox"
                checked={form.isSubAgent}
                onChange={(e) => setForm((f) => ({ ...f, isSubAgent: e.target.checked }))}
              />
              {t("agents.agent.isSubAgentLabel")}
            </label>

            {formError && <p className="form-error">{formError}</p>}

            <div className="modal-actions">
              <button onClick={handleSave} disabled={saving}>
                {t("agents.agent.saveButton")}
              </button>
              <button onClick={closeForm}>{t("agents.agent.cancelButton")}</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
