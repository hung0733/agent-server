import { Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import OverviewPage from "./pages/OverviewPage";
import AgentsPage from "./pages/AgentsPage";
import MemoryPage from "./pages/MemoryPage";
import SettingsPage from "./pages/SettingsPage";
import TasksPage from "./pages/TasksPage";
import UsagePage from "./pages/UsagePage";

function PagePlaceholder() {
  return <div className="page-placeholder panel">頁面準備中</div>;
}

export default function App() {
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
