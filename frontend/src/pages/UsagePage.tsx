import { useTranslation } from "react-i18next";
import { fetchUsage } from "../api/dashboard";
import UsageDonutLegend from "../components/usage/UsageDonutLegend";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { usagePayload } from "../mock/dashboard";

export default function UsagePage() {
  const { t } = useTranslation();
  const payload = useDashboardResource(fetchUsage, usagePayload);

  return (
    <section>
      <SectionHeader title={t("usage.title")} subtitle={t("usage.subtitle")} />
      <UsageDonutLegend total={payload.total} items={payload.items} />
    </section>
  );
}
