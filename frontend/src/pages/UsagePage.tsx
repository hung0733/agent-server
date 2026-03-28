import { useTranslation } from "react-i18next";
import { fetchUsage } from "../api/dashboard";
import UsageDonutLegend from "../components/usage/UsageDonutLegend";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { usagePayload } from "../mock/dashboard";

export default function UsagePage() {
  const { t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchUsage, usagePayload, {
    blockOnFirstLoad: true,
  });

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("usage.title")} subtitle={t("usage.subtitle")} />
      <UsageDonutLegend total={payload.total} items={payload.items} />
    </section>
  );
}
