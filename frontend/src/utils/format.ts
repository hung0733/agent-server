export function formatServerTimestamp(value: string): string {
  const match = value.match(
    /^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2}:\d{2})/,
  );

  if (!match) {
    return value;
  }

  return `${match[1]} ${match[2]}`;
}
