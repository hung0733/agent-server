import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createMessageSchedule,
  deleteMessageSchedule,
  fetchAgents,
  fetchSchedules,
  refreshMessageSchedule,
  updateMessageSchedule,
} from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import type {
  AgentsPayload,
  MessageScheduleInput,
  ScheduleItem,
  SchedulesPayload,
} from "../../types/dashboard";
import { formatServerTimestamp } from "../../utils/format";

const emptySchedulesPayload: SchedulesPayload = {
  methodSchedules: [],
  messageSchedules: [],
  source: "empty",
};

const emptyAgentsPayload: AgentsPayload = {
  agents: [],
  source: "empty",
};

const emptyForm: MessageScheduleInput = {
  agentId: "",
  name: "",
  prompt: "",
  scheduleType: "cron",
  scheduleExpression: "0 9 * * *",
  isActive: true,
};

function upsertMessageSchedule(
  payload: SchedulesPayload,
  item: ScheduleItem,
): SchedulesPayload {
  const exists = payload.messageSchedules.some((schedule) => schedule.id === item.id);
  return {
    ...payload,
    messageSchedules: exists
      ? payload.messageSchedules.map((schedule) =>
          schedule.id === item.id ? item : schedule,
        )
      : [item, ...payload.messageSchedules],
  };
}

function ScheduleCard({
  item,
  readOnly,
  onEdit,
  onToggle,
  onRefresh,
  onDelete,
}: {
  item: ScheduleItem;
  readOnly: boolean;
  onEdit?: () => void;
  onToggle?: () => void;
  onRefresh?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useTranslation();

  return (
    <article className="card schedule-card">
      <div className="schedule-card__header">
        <div>
          <h4>{item.name}</h4>
          <p>{item.prompt}</p>
        </div>
      </div>
      <dl className="schedule-card__meta">
        <div>
          <dt>{t("agents.schedule.agent")}</dt>
          <dd>{item.agentName ?? t("agents.schedule.none")}</dd>
        </div>
        <div>
          <dt>{t("agents.schedule.expression")}</dt>
          <dd>{`${item.scheduleType} - ${item.scheduleExpression}`}</dd>
        </div>
        <div>
          <dt>{t("agents.schedule.nextRun")}</dt>
          <dd>
            {item.nextRunAt
              ? formatServerTimestamp(item.nextRunAt)
              : t("agents.schedule.none")}
          </dd>
        </div>
        <div>
          <dt>{t("agents.schedule.lastRun")}</dt>
          <dd>
            {item.lastRunAt
              ? formatServerTimestamp(item.lastRunAt)
              : t("agents.schedule.none")}
          </dd>
        </div>
      </dl>
      {!readOnly ? (
        <div className="schedule-card__actions">
          <button type="button" onClick={onEdit}>
            {t("agents.schedule.editButton")}
          </button>
          <button type="button" onClick={onToggle}>
            {item.isActive
              ? t("agents.schedule.disableButton")
              : t("agents.schedule.enableButton")}
          </button>
          <button type="button" onClick={onRefresh}>
            {t("agents.schedule.refreshButton")}
          </button>
          <button type="button" onClick={onDelete}>
            {t("agents.schedule.deleteButton")}
          </button>
        </div>
      ) : null}
    </article>
  );
}

export default function ScheduleTab() {
  const { t } = useTranslation();
  const { isLoading, resource } = useDashboardResource(fetchSchedules, emptySchedulesPayload, {
    blockOnFirstLoad: true,
  });
  const { resource: agentsResource } = useDashboardResource(fetchAgents, emptyAgentsPayload);
  const [payload, setPayload] = useState<SchedulesPayload>(emptySchedulesPayload);
  const [form, setForm] = useState<MessageScheduleInput>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPayload(resource);
  }, [resource]);

  const agentOptions = useMemo(
    () => agentsResource.agents.filter((agent) => agent.isActive),
    [agentsResource.agents],
  );

  useEffect(() => {
    if (!form.agentId && agentOptions[0]) {
      setForm((current) => ({ ...current, agentId: agentOptions[0].id }));
    }
  }, [agentOptions, form.agentId]);

  function resetForm() {
    setForm({ ...emptyForm, agentId: agentOptions[0]?.id ?? "" });
    setEditingId(null);
    setShowForm(false);
    setError(null);
  }

  function handleCreateClick() {
    if (agentOptions.length === 0) {
      setError(t("agents.schedule.missingAgents"));
      return;
    }
    setEditingId(null);
    setForm({ ...emptyForm, agentId: agentOptions[0]?.id ?? "" });
    setShowForm(true);
    setError(null);
  }

  function handleEdit(item: ScheduleItem) {
    setEditingId(item.id);
    setForm({
      agentId: item.agentId ?? agentOptions[0]?.id ?? "",
      name: item.name,
      prompt: item.prompt,
      scheduleType: item.scheduleType,
      scheduleExpression: item.scheduleExpression,
      isActive: item.isActive,
    });
    setShowForm(true);
    setError(null);
  }

  async function handleSubmit() {
    setError(null);
    try {
      if (editingId) {
        const response = await updateMessageSchedule(editingId, form);
        setPayload((current) => upsertMessageSchedule(current, response.schedule));
      } else {
        const response = await createMessageSchedule(form);
        setPayload((current) => upsertMessageSchedule(current, response.schedule));
      }
      resetForm();
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : t("agents.schedule.loadError"),
      );
    }
  }

  async function handleToggle(item: ScheduleItem) {
    setError(null);
    try {
      const response = await updateMessageSchedule(item.id, {
        name: item.name,
        prompt: item.prompt,
        scheduleType: item.scheduleType,
        scheduleExpression: item.scheduleExpression,
        isActive: !item.isActive,
      });
      setPayload((current) => upsertMessageSchedule(current, response.schedule));
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : t("agents.schedule.loadError"),
      );
    }
  }

  async function handleRefresh(item: ScheduleItem) {
    setError(null);
    try {
      const response = await refreshMessageSchedule(item.id);
      setPayload((current) => upsertMessageSchedule(current, response.schedule));
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : t("agents.schedule.loadError"),
      );
    }
  }

  async function handleDelete(item: ScheduleItem) {
    if (!window.confirm(t("agents.schedule.deleteConfirm"))) {
      return;
    }
    setError(null);
    try {
      await deleteMessageSchedule(item.id);
      setPayload((current) => ({
        ...current,
        messageSchedules: current.messageSchedules.filter(
          (schedule) => schedule.id !== item.id,
        ),
      }));
      if (editingId === item.id) {
        resetForm();
      }
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : t("agents.schedule.loadError"),
      );
    }
  }

  if (isLoading) {
    return <section className="card dashboard-loading">{t("tasks.loading")}</section>;
  }

  return (
    <section className="schedule-tab">
      {error ? <div className="card settings-error">{error}</div> : null}

      <article className="schedule-section">
        <div className="schedule-section__header">
          <h3>{t("agents.schedule.messageTitle")}</h3>
          <button
            className="schedule-section__add"
            type="button"
            onClick={handleCreateClick}
          >
            {t("agents.schedule.addButton")}
          </button>
        </div>

        {showForm ? (
          <div className="card schedule-form">
            <h4>
              {editingId
                ? t("agents.schedule.formEditTitle")
                : t("agents.schedule.formCreateTitle")}
            </h4>
            <label>
              <span>{t("agents.schedule.agentLabel")}</span>
              <select
                value={form.agentId}
                onChange={(event) =>
                  setForm((current) => ({ ...current, agentId: event.target.value }))
                }
              >
                {agentOptions.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>{t("agents.schedule.nameLabel")}</span>
              <input
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
              />
            </label>
            <label>
              <span>{t("agents.schedule.promptLabel")}</span>
              <textarea
                value={form.prompt}
                onChange={(event) =>
                  setForm((current) => ({ ...current, prompt: event.target.value }))
                }
                rows={4}
              />
            </label>
            <div className="schedule-form__grid">
              <label>
                <span>{t("agents.schedule.typeLabel")}</span>
                <select
                  value={form.scheduleType}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      scheduleType: event.target.value as MessageScheduleInput["scheduleType"],
                    }))
                  }
                >
                  <option value="cron">cron</option>
                  <option value="interval">interval</option>
                </select>
              </label>
              <label>
                <span>{t("agents.schedule.expressionLabel")}</span>
                <input
                  value={form.scheduleExpression}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      scheduleExpression: event.target.value,
                    }))
                  }
                />
              </label>
            </div>
            <label className="schedule-form__checkbox">
              <input
                type="checkbox"
                checked={form.isActive}
                onChange={(event) =>
                  setForm((current) => ({ ...current, isActive: event.target.checked }))
                }
              />
              <span>{t("agents.schedule.activeLabel")}</span>
            </label>
            <div className="schedule-form__actions">
              <button type="button" onClick={resetForm}>
                {t("agents.schedule.cancelButton")}
              </button>
              <button
                type="button"
                className="schedule-section__add"
                onClick={handleSubmit}
              >
                {t("agents.schedule.saveButton")}
              </button>
            </div>
          </div>
        ) : null}

        <div className="schedule-section__list">
          {payload.messageSchedules.length === 0 ? (
            <div className="card agents-placeholder">{t("agents.schedule.emptyMessage")}</div>
          ) : null}
          {payload.messageSchedules.map((item) => (
            <ScheduleCard
              key={item.id}
              item={item}
              readOnly={false}
              onEdit={() => handleEdit(item)}
              onToggle={() => void handleToggle(item)}
              onRefresh={() => void handleRefresh(item)}
              onDelete={() => void handleDelete(item)}
            />
          ))}
        </div>
      </article>

      <article className="schedule-section">
        <div className="schedule-section__header">
          <h3>{t("agents.schedule.methodTitle")}</h3>
        </div>
        <div className="schedule-section__list">
          {payload.methodSchedules.length === 0 ? (
            <div className="card agents-placeholder">{t("agents.schedule.emptyMethod")}</div>
          ) : null}
          {payload.methodSchedules.map((item) => (
            <ScheduleCard key={item.id} item={item} readOnly />
          ))}
        </div>
      </article>
    </section>
  );
}
