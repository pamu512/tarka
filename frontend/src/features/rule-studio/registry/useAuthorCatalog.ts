import { useQuery } from "@tanstack/react-query";
import { rules } from "../../../api/client";
import type { AuthorCatalog } from "../../../domain/authorCatalog";
import { fallbackAuthorCatalog } from "../../../domain/authorCatalogFallback";
import { catalogToFields, type CatalogFieldDef } from "./catalogToFields";

export function useAuthorCatalog(tenantId?: string): {
  catalog: AuthorCatalog;
  fields: CatalogFieldDef[];
  isLoading: boolean;
  isError: boolean;
} {
  const q = useQuery({
    queryKey: ["rule-studio", "author-catalog", tenantId ?? ""],
    queryFn: async () => {
      try {
        return await rules.authorCatalog(tenantId);
      } catch {
        return fallbackAuthorCatalog();
      }
    },
    staleTime: 60_000,
  });

  const catalog = q.data ?? fallbackAuthorCatalog();
  return {
    catalog,
    fields: catalogToFields(catalog),
    isLoading: q.isLoading,
    isError: q.isError,
  };
}
