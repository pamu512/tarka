import type { ApolloClient, NormalizedCacheObject } from "@apollo/client";
import type { QueryClient } from "@tanstack/react-query";

export interface RegisteredDataCaches {
  readonly queryClient: QueryClient;
  readonly apolloClient: ApolloClient<NormalizedCacheObject>;
}

let registered: RegisteredDataCaches | null = null;

export function registerDataCaches(caches: RegisteredDataCaches): void {
  registered = caches;
}

export function unregisterDataCaches(): void {
  registered = null;
}

function assertRegistered(): RegisteredDataCaches {
  if (!registered) {
    throw new Error(
      "Data caches are not registered. Wrap the app (or test harness) with DataCachesProvider before switching runtime tier.",
    );
  }
  return registered;
}

/**
 * Purges TanStack Query and Apollo in-memory caches. Call after runtime tier changes so stale
 * micro/production responses cannot leak across environments.
 */
export async function purgeAllDataCaches(): Promise<void> {
  const { queryClient, apolloClient } = assertRegistered();
  await queryClient.cancelQueries();
  queryClient.clear();
  await apolloClient.clearStore();
}

export function getRegisteredDataCaches(): RegisteredDataCaches | null {
  return registered;
}
