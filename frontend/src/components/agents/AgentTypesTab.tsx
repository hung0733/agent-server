import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  createAgentType,
  deleteAgentType,
  fetchAgentTypes,
  updateAgentType,
} from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { agentTypesPayload } from "../../mock/dashboard";
import type { AgentTypeItem } from "../../types/dashboard";

interface FormState {
  name: string;
  description: string;
  isActive: boolean;
}

const EMPTY_FORM: FormState = { name: "", description: "", isActive: true };

export default function AgentTypesTab() {
  const { t } = useTranslation();
  const { isLoading, resource } = useDashboardResource(fetchAgentTypes, agentTypesPayload, {
    blockOnFirstLoad: true,
  });

  const [items, setItems] = useState(agentTypesPayload.agentTypes);
  const [editing, setEditing] = useState<AgentTypeItem | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setItems(resource.agentTypes);
  }, [resource]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setShowForm(true);
  }

  function openEdit(item: AgentTypeItem) {
    setEditing(item);
    setForm({ name: item.name, description: item.description ?? "", isActive: item.isActive });
    setFormError(null);
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditing(null);
    setFormError(null);
  }

  async function handleSave() {
    if (!form.name.trim()) {
      setFormError(t("agents.agentType.errorNameRequired"));
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        const result = await updateAgentType(editing.id, {
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          isActive: form.isActive,
        });
        setItems((prev) => prev.map((i) => (i.id === editing.id ? result.agentType : i)));
      } else {
        const result = await createAgentType({
          name: form.name.trim(),
          description: form.description.trim() || undefined,
          isActive: form.isActive,
        });
        setItems((prev) => [...prev, result.agentType]);
      }
      closeForm();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("name_already_exists")) {
        setFormError(t("agents.agentType.errorNameExists"));
      } else {
        setFormError(msg);
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item: AgentTypeItem) {
    if (!window.confirm(t("agents.agentType.deleteConfirm", { name: item.name }))) return;
    await deleteAgentType(item.id);
    setItems((prev) => prev.filter((i) => i.id !== item.id));
  }

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入...</section>;
  }

  return (
    <section className="agent-types-tab">
      <div className="agent-types-header">
        <button className="btn btn-primary" onClick={openCreate}>
          {t("agents.agentType.addButton")}
        </button>
      </div>

      {items.length === 0 ? (
        <p className="agent-types-empty">{t("agents.agentType.empty")}</p>
      ) : (
        <table className="agent-types-table">
          <thead>
            <tr>
              <th>{t("agents.agentType.colName")}</th>
              <th>{t("agents.agentType.colDescription")}</th>
              <th>{t("agents.agentType.colActive")}</th>
              <th>{t("agents.agentType.colActions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.name}</td>
                <td>{item.description ?? "—"}</td>
                <td>
                  <input type="checkbox" checked={item.isActive} readOnly aria-label={item.name} />
                </td>
                <td>
                  <button onClick={() => openEdit(item)}>
                    {t("agents.agentType.editAction")}
                  </button>
                  <button onClick={() => handleDelete(item)}>
                    {t("agents.agentType.deleteAction")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showForm && (
        <div role="dialog" aria-modal="true" className="agent-type-modal">
          <h2>{editing ? t("agents.agentType.editTitle") : t("agents.agentType.createTitle")}</h2>

          <label>
            {t("agents.agentType.nameLabel")}
            <input
              type="text"
              value={form.name}
              placeholder={t("agents.agentType.namePlaceholder")}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </label>

          <label>
            {t("agents.agentType.descriptionLabel")}
            <input
              type="text"
              value={form.description}
              placeholder={t("agents.agentType.descriptionPlaceholder")}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </label>

          <label>
            <input
              type="checkbox"
              checked={form.isActive}
              onChange={(e) => setForm((f) => ({ ...f, isActive: e.target.checked }))}
            />
            {t("agents.agentType.isActiveLabel")}
          </label>

          {formError && <p className="form-error">{formError}</p>}

          <div className="modal-actions">
            <button onClick={handleSave} disabled={saving}>
              {t("agents.agentType.saveButton")}
            </button>
            <button onClick={closeForm}>{t("agents.agentType.cancelButton")}</button>
          </div>
        </div>
      )}
    </section>
  );
}
