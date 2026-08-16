import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useLayoutEffect, useMemo, type ReactNode } from "react";

import { registerDataCaches, unregisterDataCaches } from "@/lib/dataCachesRegistry";

export function DataCachesProvider({ children }: { children: ReactNode }): React.ReactElement {
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
    [],
  );

  useLayoutEffect(() => {
    registerDataCaches({ queryClient });
    return () => {
      unregisterDataCaches();
    };
  }, [queryClient]);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
