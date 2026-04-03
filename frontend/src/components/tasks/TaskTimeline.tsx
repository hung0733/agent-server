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

  // Format summary: add line breaks after certain patterns
  const formattedSummary = item.summary
    // Add line break after "。 **" pattern (before new section headings)
    .replace(/。\s*\*\*/g, '。\n\n**')
    // Add line break after bullet points that start with "* **"
    .replace(/\*\s+\*\*/g, '\n* **')
    // Ensure numbered lists have line breaks (e.g., "1. xxx 2. yyy" -> "1. xxx\n2. yyy")
    .replace(/(\d+\.\s+[^\n]+?)\s+(\d+\.)/g, '$1\n$2');

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
            >
              {formattedSummary}
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
          <div className="timeline-item__content-full">
            {formattedSummary}
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
