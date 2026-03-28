import { useTranslation } from "react-i18next";
import { fetchTasks } from "../api/dashboard";
import TaskTimeline from "../components/tasks/TaskTimeline";
import SectionHeader from "../components/ui/SectionHeader";
import { useDashboardResource } from "../hooks/useDashboardResource";
import { tasksPayload } from "../mock/dashboard";

export default function TasksPage() {
  const { t } = useTranslation();
  const payload = useDashboardResource(fetchTasks, tasksPayload);

  return (
    <section>
      <SectionHeader title={t("tasks.title")} subtitle={t("tasks.subtitle")} />
      <TaskTimeline items={payload.items} />
    </section>
  );
}
