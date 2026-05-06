import { ApolloClient, ApolloProvider, HttpLink, InMemoryCache } from "@apollo/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useLayoutEffect, useMemo, type ReactNode } from "react";

import { registerDataCaches, unregisterDataCaches } from "@/lib/dataCachesRegistry";

function resolveGraphqlHttpUri(): string {
  const v = import.meta.env.VITE_GRAPHQL_URI?.trim();
  if (v) {
    return v;
  }
  return "/graphql";
}

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

  const apolloClient = useMemo(
    () =>
      new ApolloClient({
        link: new HttpLink({
          uri: resolveGraphqlHttpUri(),
          credentials: "same-origin",
        }),
        cache: new InMemoryCache(),
        defaultOptions: {
          watchQuery: { fetchPolicy: "network-only" },
          query: { fetchPolicy: "network-only" },
        },
      }),
    [],
  );

  useLayoutEffect(() => {
    registerDataCaches({ queryClient, apolloClient });
    return () => {
      unregisterDataCaches();
    };
  }, [queryClient, apolloClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <ApolloProvider client={apolloClient}>{children}</ApolloProvider>
    </QueryClientProvider>
  );
}
