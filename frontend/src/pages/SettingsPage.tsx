import { useTranslation } from "react-i18next";
import { fetchSettings } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { settingsPayload } from "../mock/dashboard";

export default function SettingsPage() {
  const { t } = useTranslation();
  const payload = useDashboardResource(fetchSettings, settingsPayload);

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
