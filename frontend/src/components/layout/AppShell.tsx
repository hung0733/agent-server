import { PropsWithChildren } from "react";
import { useTranslation } from "react-i18next";

import { fetchOverview } from "../../api/dashboard";
import { DashboardOverviewContext } from "../../context/dashboard-overview";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { overviewPayload } from "../../mock/dashboard";
import Sidebar from "./Sidebar";
import StatusRail from "./StatusRail";

function formatDateTime(value: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function AppShell({ children }: PropsWithChildren) {
  const { i18n, t } = useTranslation();
  const { isLoading, resource: overview } = useDashboardResource(fetchOverview, overviewPayload, {
    blockOnFirstLoad: true,
  });

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        {isLoading ? <section className="card dashboard-loading">正在載入控制台...</section> : (
          <DashboardOverviewContext.Provider value={overview}>
            <header className="app-header">
              <span>
                {t("shell.lastUpdated")}: {formatDateTime(overview.shellMeta.lastUpdatedAt, i18n.language)}
              </span>
            </header>
            {children}
          </DashboardOverviewContext.Provider>
        )}
      </main>
      {isLoading ? null : <StatusRail railSummary={overview.railSummary} status={overview.summary.status} />}
    </div>
  );
}
