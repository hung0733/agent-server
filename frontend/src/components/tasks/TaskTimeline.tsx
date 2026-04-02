import { useState } from "react";
import { useTranslation } from "react-i18next";
import { formatServerTimestamp } from "../../utils/format";
import { TimelineItem } from "../../types/dashboard";
import EmptyState from "../ui/EmptyState";
import Badge from "../ui/Badge";

const toneMap = {
  healthy: "healthy",
  warning: "warning",
  danger: "danger",
  idle: "warning",
} as const;

function TimelineItemCard({ item }: { item: TimelineItem }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [needsExpand, setNeedsExpand] = useState(false);
  const previewRef = useState<HTMLDivElement | null>(null)[0];

  // Check if content is actually truncated
  const handlePreviewRef = (element: HTMLDivElement | null) => {
    if (element) {
      // Check if the content height exceeds the clamped height
      const isTruncated = element.scrollHeight > element.clientHeight;
      setNeedsExpand(isTruncated);
    }
  };

  return (
    <article className="card timeline-item">
      <div className="timeline-item__header">
        <div>
          <h3>{item.title}</h3>
          <p>{item.sourceAgent} -&gt; {item.targetAgent}</p>
          {item.group ? <p className="timeline-item__group">{item.group}</p> : null}
        </div>
        <div className="timeline-item__meta">
          <Badge tone={toneMap[item.status]} label={formatServerTimestamp(item.timestamp)} />
        </div>
      </div>
      <div className="timeline-item__content">
        {!isExpanded ? (
          <>
            <div
              ref={handlePreviewRef}
              className="timeline-item__content-preview"
              style={{
                display: '-webkit-box',
                WebkitLineClamp: 4,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
                color: '#ffffff',
                lineHeight: 1.6,
                whiteSpace: 'pre-wrap'
              }}
            >
              {item.summary}
            </div>
            {needsExpand && (
              <button
                className="timeline-item__expand-btn"
                onClick={() => setIsExpanded(true)}
              >
                ▼ 展開全文
              </button>
            )}
          </>
        ) : (
          <div
            className="timeline-item__content-full"
            style={{
              color: '#ffffff',
              lineHeight: 1.6,
              whiteSpace: 'pre-wrap'
            }}
          >
            {item.summary}
          </div>
        )}
      </div>
    </article>
  );
}

export default function TaskTimeline({ items }: { items: TimelineItem[] }) {
  const { t } = useTranslation();

  if (items.length === 0) {
    return <EmptyState title={t("tasks.emptyTitle")} body={t("tasks.emptyBody")} />;
  }

  return (
    <div className="timeline">
      {items.map((item) => (
        <TimelineItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}
