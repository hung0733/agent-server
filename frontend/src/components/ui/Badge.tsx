interface BadgeProps {
  tone: "healthy" | "warning" | "danger";
  label: string;
}

export default function Badge({ tone, label }: BadgeProps) {
  return <span className={`status-pill status-pill--${tone}`}>{label}</span>;
}
