import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  createSettingsEndpoint,
  createAuthKey,
  deleteAuthKey,
  deleteSettingsEndpoint,
  fetchSettings,
  regenerateAuthKey,
  saveSettingsMapping,
  updateAuthKey,
  updateSettingsEndpoint,
} from "../api/dashboard";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { settingsPayload } from "../mock/dashboard";
import { SettingsPayload } from "../types/dashboard";

type EndpointFormState = {
  id?: string;
  name: string;
  baseUrl: string;
  modelName: string;
  apiKey: string;
  isActive: boolean;
};

const emptyForm: EndpointFormState = {
  name: "",
  baseUrl: "",
  modelName: "",
  apiKey: "",
  isActive: true,
};

type AuthKeyFormState = {
  name: string;
  expiresAt: string;
};

const emptyAuthKeyForm: AuthKeyFormState = {
  name: "",
  expiresAt: "",
};

function formatSettingDate(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-HK");
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchSettings, settingsPayload, {
    blockOnFirstLoad: true,
  });
  const [settings, setSettings] = useState<SettingsPayload>(settingsPayload);
  const [form, setForm] = useState<EndpointFormState>(emptyForm);
  const [authKeyForm, setAuthKeyForm] = useState<AuthKeyFormState>(emptyAuthKeyForm);
  const [error, setError] = useState<string | null>(null);
  const [rawKeyNotice, setRawKeyNotice] = useState<string | null>(null);

  useEffect(() => {
    setSettings(payload);
  }, [payload]);

  const endpointNameMap = useMemo(
    () => new Map(settings.endpoints.map((endpoint) => [endpoint.id, `${endpoint.name} (${endpoint.modelName})`])),
    [settings.endpoints],
  );

  async function submitEndpoint() {
    setError(null);
    setRawKeyNotice(null);
    const body = {
      name: form.name,
      baseUrl: form.baseUrl,
      modelName: form.modelName,
      apiKey: form.apiKey,
      isActive: form.isActive,
    };
    try {
      if (form.id) {
        const response = await updateSettingsEndpoint(form.id, body);
        setSettings((current) => ({
          ...current,
          endpoints: current.endpoints.map((endpoint) =>
            endpoint.id === form.id ? response.endpoint : endpoint,
          ),
        }));
      } else {
        const response = await createSettingsEndpoint(body);
        setSettings((current) => ({
          ...current,
          endpoints: [...current.endpoints, response.endpoint],
        }));
      }
      setForm(emptyForm);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "儲存失敗");
    }
  }

  async function removeEndpoint(endpointId: string) {
    setError(null);
    setRawKeyNotice(null);
    try {
      await deleteSettingsEndpoint(endpointId);
      setSettings((current) => ({
        ...current,
        endpoints: current.endpoints.filter((endpoint) => endpoint.id !== endpointId),
      }));
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "刪除失敗");
    }
  }

  async function updateMapping(
    groupId: string,
    difficultyLevel: number,
    involvesSecrets: boolean,
    endpointId: string,
  ) {
    setError(null);
    setRawKeyNotice(null);
    try {
      const response = await saveSettingsMapping({
        groupId,
        difficultyLevel,
        involvesSecrets,
        endpointId: endpointId || null,
      });
      setSettings((current) => ({
        ...current,
        groups: current.groups.map((group) => {
          if (group.id !== groupId) return group;
          const slots = group.slots.filter(
            (slot) => !(slot.difficultyLevel === difficultyLevel && slot.involvesSecrets === involvesSecrets),
          );
          return response.mapping ? { ...group, slots: [...slots, response.mapping] } : { ...group, slots };
        }),
      }));
    } catch (mappingError) {
      setError(mappingError instanceof Error ? mappingError.message : "更新 mapping 失敗");
    }
  }

  async function submitAuthKey() {
    setError(null);
    try {
      const response = await createAuthKey({
        name: authKeyForm.name || null,
        expiresAt: authKeyForm.expiresAt || null,
      });
      setSettings((current) => ({ ...current, authKeys: [response.key, ...current.authKeys] }));
      setRawKeyNotice(response.rawKey);
      setAuthKeyForm(emptyAuthKeyForm);
    } catch (authKeyError) {
      setError(authKeyError instanceof Error ? authKeyError.message : "建立 Auth Key 失敗");
    }
  }

  async function toggleAuthKey(keyId: string, isActive: boolean) {
    setError(null);
    try {
      const response = await updateAuthKey(keyId, { isActive: !isActive });
      setSettings((current) => ({
        ...current,
        authKeys: current.authKeys.map((item) => (item.id === keyId ? response.key : item)),
      }));
    } catch (authKeyError) {
      setError(authKeyError instanceof Error ? authKeyError.message : "更新 Auth Key 失敗");
    }
  }

  async function removeAuthKey(keyId: string) {
    setError(null);
    try {
      await deleteAuthKey(keyId);
      setSettings((current) => ({
        ...current,
        authKeys: current.authKeys.filter((item) => item.id !== keyId),
      }));
    } catch (authKeyError) {
      setError(authKeyError instanceof Error ? authKeyError.message : "刪除 Auth Key 失敗");
    }
  }

  async function regenerateKey(keyId: string, name: string, expiresAt: string | null) {
    setError(null);
    try {
      const response = await regenerateAuthKey(keyId, { name, expiresAt });
      setSettings((current) => ({
        ...current,
        authKeys: [response.key, ...current.authKeys.map((item) => (item.id === keyId ? { ...item, isActive: false } : item))],
      }));
      setRawKeyNotice(response.rawKey);
    } catch (authKeyError) {
      setError(authKeyError instanceof Error ? authKeyError.message : "重新產生 Auth Key 失敗");
    }
  }

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      {error ? <article className="card settings-error">{error}</article> : null}
      {rawKeyNotice ? (
        <article className="card settings-secret-panel">
          <h3>新 Auth Key（只顯示一次）</h3>
          <code>{rawKeyNotice}</code>
        </article>
      ) : null}

      <article className="card settings-section">
        <div className="settings-section__header">
          <div>
            <h3>LLM Endpoint 管理</h3>
            <p>新增 / 編輯 / 刪除 endpoint，mapping 另外設定。</p>
          </div>
        </div>

        <div className="settings-endpoint-form">
          <label className="settings-field">
            <span>名稱</span>
            <input placeholder="例如：Local Qwen" value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} />
          </label>
          <label className="settings-field">
            <span>Base URL</span>
            <input placeholder="http://localhost:8601/v1" value={form.baseUrl} onChange={(event) => setForm((current) => ({ ...current, baseUrl: event.target.value }))} />
          </label>
          <label className="settings-field">
            <span>Model name</span>
            <input placeholder="qwen3.5-35b-a3b" value={form.modelName} onChange={(event) => setForm((current) => ({ ...current, modelName: event.target.value }))} />
          </label>
          <label className="settings-field">
            <span>API key</span>
            <input placeholder="留空代表本地或不更新" value={form.apiKey} onChange={(event) => setForm((current) => ({ ...current, apiKey: event.target.value }))} />
          </label>
          <div className="settings-form-footer">
            <label className="settings-checkbox" htmlFor="endpoint-active">
              <input id="endpoint-active" checked={form.isActive} type="checkbox" onChange={(event) => setForm((current) => ({ ...current, isActive: event.target.checked }))} />
              <span>啟用</span>
            </label>
            <div className="settings-form-actions">
              {form.id ? (
                <button className="button" onClick={() => setForm(emptyForm)} type="button">
                  取消編輯
                </button>
              ) : null}
              <button className="button button--primary" onClick={submitEndpoint} type="button">
                {form.id ? "更新 Endpoint" : "建立 Endpoint"}
              </button>
            </div>
          </div>
        </div>

        <div className="settings-endpoint-list">
          {settings.endpoints.map((endpoint) => (
            <article className="settings-endpoint-item" key={endpoint.id}>
              <div>
                <strong>{endpoint.name}</strong>
                <p>{endpoint.modelName}</p>
                <p>{endpoint.baseUrl}</p>
              </div>
              <div className="settings-endpoint-item__meta">
                <span>{endpoint.apiKeyConfigured ? "API key 已設" : "API key 未設"}</span>
                <span>{endpoint.isActive ? "啟用中" : "已停用"}</span>
              </div>
              <div className="settings-endpoint-item__actions">
                <button type="button" onClick={() => setForm({ id: endpoint.id, name: endpoint.name, baseUrl: endpoint.baseUrl, modelName: endpoint.modelName, apiKey: "", isActive: endpoint.isActive })}>
                  編輯
                </button>
                <button type="button" onClick={() => removeEndpoint(endpoint.id)}>
                  刪除
                </button>
              </div>
            </article>
          ))}
        </div>
      </article>

      <article className="card settings-section">
        <div className="settings-section__header">
          <div>
            <h3>Group / Level Mapping</h3>
            <p>每個 group / level 分開設定 endpoint。</p>
          </div>
        </div>

        <div className="settings-group-list">
          {settings.groups.map((group) => {
            const slotMap = new Map(
              group.slots.map((slot) => [`${slot.difficultyLevel}-${slot.involvesSecrets}`, slot]),
            );
            return (
              <section className="settings-group-card" key={group.id}>
                <h4>{group.name}</h4>
                {[1, 2, 3].flatMap((level) => [false, true].map((involvesSecrets) => ({ level, involvesSecrets }))).map(({ level, involvesSecrets }) => {
                  const key = `${level}-${involvesSecrets}`;
                  const slot = slotMap.get(key);
                  return (
                    <label className="settings-mapping-row" key={key}>
                      <span>{`L${level} / ${involvesSecrets ? "Secrets" : "General"}`}</span>
                      <select
                        value={slot?.endpointId ?? ""}
                        onChange={(event) => updateMapping(group.id, level, involvesSecrets, event.target.value)}
                      >
                        <option value="">未設定</option>
                        {settings.endpoints.map((endpoint) => (
                          <option key={endpoint.id} value={endpoint.id}>
                            {endpoint.name} ({endpoint.modelName})
                          </option>
                        ))}
                      </select>
                      <small>{slot?.endpointId ? endpointNameMap.get(slot.endpointId) : "未綁定 endpoint"}</small>
                    </label>
                  );
                })}
              </section>
            );
          })}
        </div>
      </article>

      <article className="card settings-section">
        <div className="settings-section__header">
          <div>
            <h3>Auth Keys</h3>
            <p>建立、停用、刪除或重新產生你自己嘅 dashboard auth key。</p>
          </div>
        </div>

        <div className="settings-endpoint-form">
          <label className="settings-field">
            <span>名稱</span>
            <input value={authKeyForm.name} onChange={(event) => setAuthKeyForm((current) => ({ ...current, name: event.target.value }))} placeholder="例如：Dashboard main" />
          </label>
          <label className="settings-field">
            <span>到期時間</span>
            <input type="datetime-local" value={authKeyForm.expiresAt} onChange={(event) => setAuthKeyForm((current) => ({ ...current, expiresAt: event.target.value }))} />
          </label>
          <div className="settings-form-footer settings-form-footer--single">
            <div className="settings-form-actions">
              <button className="button button--primary" type="button" onClick={submitAuthKey}>
                建立 Auth Key
              </button>
            </div>
          </div>
        </div>

        <div className="settings-endpoint-list">
          {settings.authKeys.map((key) => (
            <article className="settings-endpoint-item" key={key.id}>
              <div>
                <strong>{key.name}</strong>
                <p>建立時間：{formatSettingDate(key.createdAt)}</p>
                <p>最後使用：{formatSettingDate(key.lastUsedAt)}</p>
                <p>到期時間：{formatSettingDate(key.expiresAt)}</p>
              </div>
              <div className="settings-endpoint-item__meta">
                <span>{key.isActive ? "啟用中" : "已停用"}</span>
              </div>
              <div className="settings-endpoint-item__actions">
                <button type="button" onClick={() => toggleAuthKey(key.id, key.isActive)}>
                  {key.isActive ? "停用" : "啟用"}
                </button>
                <button type="button" onClick={() => regenerateKey(key.id, key.name, key.expiresAt)}>
                  重新產生
                </button>
                <button type="button" onClick={() => removeAuthKey(key.id)}>
                  刪除
                </button>
              </div>
            </article>
          ))}
        </div>
      </article>
    </section>
  );
}
