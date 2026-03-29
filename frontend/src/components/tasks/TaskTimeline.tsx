import { useTranslation } from "react-i18next";
import { TimelineItem } from "../../types/dashboard";
import Badge from "../ui/Badge";

const toneMap = {
  healthy: "healthy",
  warning: "warning",
  danger: "danger",
  idle: "warning",
} as const;

export default function TaskTimeline({ items }: { items: TimelineItem[] }) {
  const { t } = useTranslation();

  return (
    <div className="timeline">
      {items.map((item) => (
        <article key={item.id} className="card timeline-item">
          <div className="timeline-item__header">
            <div>
              <h3>{item.title}</h3>
              <p>{item.sourceAgent} -&gt; {item.targetAgent}</p>
              {item.group ? <p className="timeline-item__group">{item.group}</p> : null}
            </div>
            <div className="timeline-item__meta">
              <Badge tone={toneMap[item.status]} label={item.timestamp} />
            </div>
          </div>
          {item.messageSnippet ? (
            <p className="timeline-item__snippet">{item.messageSnippet}</p>
          ) : null}
          <p className="timeline-item__summary">{item.summary}</p>
          <details>
            <summary>{t("tasks.technicalDetails")}</summary>
            <p>{item.technicalDetails}</p>
          </details>
        </article>
      ))}
    </div>
  );
}
