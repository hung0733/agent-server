import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import { DASHBOARD_AUTH_EXPIRED_EVENT, fetchOverviewWithApiKey } from "./api/dashboard";
import AppShell from "./components/layout/AppShell";
import { clearStoredApiKey, getStoredApiKey, setStoredApiKey } from "./lib/auth";
import OverviewPage from "./pages/OverviewPage";
import AgentsPage from "./pages/AgentsPage";
import LoginPage from "./pages/LoginPage";
import MemoryPage from "./pages/MemoryPage";
import SettingsPage from "./pages/SettingsPage";
import TasksPage from "./pages/TasksPage";
import UsagePage from "./pages/UsagePage";

function PagePlaceholder() {
  return <div className="page-placeholder panel">頁面準備中</div>;
}

export default function App() {
  const [apiKey, setApiKey] = useState(() => getStoredApiKey());
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    const handleAuthExpired = () => {
      clearStoredApiKey();
      setApiKey("");
      setLoginError("API key 無效、已過期，或你未有控制台存取權限。");
    };

    window.addEventListener(DASHBOARD_AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => {
      window.removeEventListener(DASHBOARD_AUTH_EXPIRED_EVENT, handleAuthExpired);
    };
  }, []);

  if (!apiKey) {
    return (
      <LoginPage
        errorMessage={loginError}
        onLogin={async (value) => {
          try {
            await fetchOverviewWithApiKey(value);
            setStoredApiKey(value);
            setApiKey(value);
            setLoginError(null);
          } catch {
            clearStoredApiKey();
            setApiKey("");
            setLoginError("API key 無效、已過期，或你未有控制台存取權限。");
          }
        }}
      />
    );
  }

  return (
    <AppShell onLogout={() => {
      clearStoredApiKey();
      setApiKey("");
      setLoginError(null);
    }}>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/usage" element={<UsagePage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<PagePlaceholder />} />
      </Routes>
    </AppShell>
  );
}
