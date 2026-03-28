import { useTranslation } from "react-i18next";
import Badge from "./Badge";

interface StatCardProps {
  title: string;
  value: number;
  note: string;
  status?: "healthy" | "warning" | "danger";
}

export default function StatCard({ title, value, note, status = "healthy" }: StatCardProps) {
  const { t } = useTranslation();

  const labelByStatus = {
    healthy: t("common.badge.stable"),
    warning: t("common.badge.watch"),
    danger: t("common.badge.error"),
  };

  return (
    <article className="card stat-card">
      <div className="stat-card__header">
        <p className="stat-card__title">{title}</p>
        <Badge tone={status} label={labelByStatus[status]} />
      </div>
      <p className="stat-card__value">{value}</p>
      <p className="stat-card__note">{note}</p>
    </article>
  );
}
