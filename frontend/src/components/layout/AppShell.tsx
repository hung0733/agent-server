import { PropsWithChildren } from "react";
import { useTranslation } from "react-i18next";

import { fetchOverview } from "../../api/dashboard";
import { useDashboardResource } from "../../hooks/useDashboardResource";
import { formatDateTime } from "../../lib/format";
import { overviewPayload } from "../../mock/dashboard";
import Sidebar from "./Sidebar";
import StatusRail from "./StatusRail";

export default function AppShell({ children }: PropsWithChildren) {
  const { i18n, t } = useTranslation();
  const overview = useDashboardResource(fetchOverview, overviewPayload);

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <header className="app-header">
          <span>
            {t("shell.lastUpdated")}: {formatDateTime(overview.shellMeta.lastUpdatedAt, i18n.language)}
          </span>
        </header>
        {children}
      </main>
      <StatusRail railSummary={overview.railSummary} status={overview.summary.status} />
    </div>
  );
}
