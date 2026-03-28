import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import { DASHBOARD_AUTH_EXPIRED_EVENT } from "./api/dashboard";
import { getStoredApiKey, setStoredApiKey } from "./lib/auth";
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

  useEffect(() => {
    const handleAuthExpired = () => {
      setApiKey("");
    };

    window.addEventListener(DASHBOARD_AUTH_EXPIRED_EVENT, handleAuthExpired);
    return () => {
      window.removeEventListener(DASHBOARD_AUTH_EXPIRED_EVENT, handleAuthExpired);
    };
  }, []);

  if (!apiKey) {
    return <LoginPage onLogin={(value) => {
      setStoredApiKey(value);
      setApiKey(value);
    }} />;
  }

  return (
    <AppShell>
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
