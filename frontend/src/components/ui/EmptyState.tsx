interface EmptyStateProps {
  title: string;
  body: string;
}

export default function EmptyState({ title, body }: EmptyStateProps) {
  return (
    <div className="card empty-state">
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}
