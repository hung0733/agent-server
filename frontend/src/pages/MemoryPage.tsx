import { useTranslation } from "react-i18next";
import { fetchMemory } from "../api/dashboard";
import EmptyState from "../components/ui/EmptyState";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { memoryPayload } from "../mock/dashboard";

export default function MemoryPage() {
  const { t } = useTranslation();
  const payload = useDashboardResource(fetchMemory, memoryPayload);

  return (
    <section>
      <SectionHeader title={t("memory.title")} subtitle={t("memory.subtitle")} />
      <EmptyState title={payload.title || t("memory.emptyTitle")} body={payload.body || t("memory.emptyBody")} />
    </section>
  );
}
