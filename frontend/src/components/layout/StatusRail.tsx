import { useTranslation } from "react-i18next";

import { RailSummary, SystemStatus } from "../../types/dashboard";
import Card from "../ui/Card";
import Badge from "../ui/Badge";

export default function StatusRail({
  railSummary,
  status = "healthy",
}: {
  railSummary: RailSummary;
  status?: SystemStatus;
}) {
  const { t } = useTranslation();

  const tone = status === "danger" ? "danger" : status === "warning" ? "warning" : "healthy";

  return (
    <aside className="status-rail">
      <Card>
        <h3>{t("rail.currentStatus")}</h3>
        <p style={{ marginTop: "12px", color: "var(--text-2)" }}>{t("rail.currentStatusSummary")}</p>
        <div style={{ marginTop: "16px" }}>
          <Badge tone={tone} label={t(`common.status.${status === "danger" ? "danger" : status === "warning" ? "warning" : "healthy"}`)} />
        </div>
      </Card>
      <Card>
        <h3>{t("rail.todayUsage")}</h3>
        <p style={{ marginTop: "12px", color: "var(--text-2)" }}>{railSummary.usageText}</p>
      </Card>
      <Card>
        <h3>{t("rail.activeAgents")}</h3>
        <p style={{ marginTop: "12px", color: "var(--text-2)" }}>{railSummary.activeAgentNames}</p>
      </Card>
    </aside>
  );
}
