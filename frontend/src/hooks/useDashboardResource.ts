import { useEffect, useState } from "react";

export function useDashboardResource<T>(
  loader: () => Promise<T>,
  fallback: T,
): T {
  const [resource, setResource] = useState<T>(fallback);

  useEffect(() => {
    let cancelled = false;

    void loader()
      .then((payload) => {
        if (!cancelled) {
          setResource(payload);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setResource(fallback);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fallback, loader]);

  return resource;
}
