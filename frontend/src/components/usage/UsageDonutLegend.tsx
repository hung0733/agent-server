import { useTranslation } from "react-i18next";
import { UsageLegendItem } from "../../types/dashboard";

export default function UsageDonutLegend({
  total,
  items,
}: {
  total: number;
  items: UsageLegendItem[];
}) {
  const { t } = useTranslation();
  const segments = items
    .map((item, index) => {
      const start = items.slice(0, index).reduce((sum, current) => sum + current.percentage, 0);
      const end = start + item.percentage;
      return `${item.color} ${start}% ${end}%`;
    })
    .join(", ");

  return (
    <section className="usage-legend">
      <div
        className="usage-legend__donut"
        role="img"
        aria-label={t("usage.chartLabel")}
        style={{ background: `conic-gradient(${segments}, rgba(255, 255, 255, 0.08) ${items.reduce((sum, item) => sum + item.percentage, 0)}% 100%)` }}
      >
        <div>
          <strong>{t("usage.totalLabel")}</strong>
          <span>{total.toLocaleString("en-US")} 用量</span>
        </div>
      </div>
      <ul className="usage-legend__list">
        {items.map((item) => (
          <li key={item.label}>
            <span className="usage-legend__item-label">
              <i style={{ background: item.color }} />
              {item.label}
            </span>
            <span>{item.percentage.toFixed(2)}%</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
