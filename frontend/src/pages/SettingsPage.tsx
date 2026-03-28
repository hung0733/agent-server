import { useTranslation } from "react-i18next";
import { fetchSettings } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { settingsPayload } from "../mock/dashboard";

export default function SettingsPage() {
  const { t } = useTranslation();
  const { isLoading, resource: payload } = useDashboardResource(fetchSettings, settingsPayload, {
    blockOnFirstLoad: true,
  });

  if (isLoading) {
    return <section className="card dashboard-loading">正在載入控制台...</section>;
  }

  return (
    <section>
      <SectionHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />
      <EmptyState
        title={t("settings.emptyTitle")}
        body={`${t("settings.emptyBody")} (${payload.locales.join(", ")})`}
      />
    </section>
  );
}
