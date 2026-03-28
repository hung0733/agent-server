import { useEffect, useState } from "react";

export function useDashboardResource<T>(
  loader: () => Promise<T>,
  fallback: T,
  options?: {
    initialData?: T;
    blockOnFirstLoad?: boolean;
  },
): { resource: T; isLoading: boolean } {
  const [resource, setResource] = useState<T>(options?.initialData ?? fallback);
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(options?.blockOnFirstLoad));

  useEffect(() => {
    let cancelled = false;

    if (options?.blockOnFirstLoad) {
      setIsLoading(true);
    }

    void loader()
      .then((payload) => {
        if (!cancelled) {
          setResource(payload);
          setIsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setResource(fallback);
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fallback, loader, options?.blockOnFirstLoad]);

  return { resource, isLoading };
}
