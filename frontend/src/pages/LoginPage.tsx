import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

export default function LoginPage({ onLogin }: { onLogin: (apiKey: string) => void }) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (apiKey.trim()) {
      onLogin(apiKey.trim());
    }
  };

  return (
    <div className="login-shell">
      <section className="login-layout">
        <aside className="card login-info" data-testid="login-info-panel">
          <span className="login-card__eyebrow">OpenClaw Dashboard</span>
          <div className="login-info__copy">
            <h1>{t("auth.loginTitle")}</h1>
            <p>{t("auth.loginBody")}</p>
          </div>
          <ul className="login-info__meta">
            <li className="login-info__meta-item">
              <strong>Scoped Access</strong>
              <span>只顯示你所屬 user 嘅 agents、用量與控制台資料。</span>
            </li>
            <li className="login-info__meta-item">
              <strong>Session Only</strong>
              <span>API key 只存於目前 browser session，重新開頁需重新登入。</span>
            </li>
          </ul>
        </aside>

        <form className="card login-card" onSubmit={handleSubmit}>
          <div className="login-card__intro">
            <h2>{t("auth.apiKeyLabel")}</h2>
            <p>輸入有效 key 後即可進入專屬控制台。</p>
          </div>
          <div className="login-card__form" data-testid="login-form-stack">
            <label className="login-card__label" htmlFor="dashboard-api-key">
              {t("auth.apiKeyLabel")}
            </label>
            <input
              id="dashboard-api-key"
              name="apiKey"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="sk-live-..."
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
            <div className="login-card__actions">
              <button type="submit">{t("auth.loginButton")}</button>
            </div>
          </div>
        </form>
      </section>
    </div>
  );
}
