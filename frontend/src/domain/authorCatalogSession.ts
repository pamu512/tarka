import { rules } from "../api/client";
import type { AuthorCatalog } from "./authorCatalog";
import { fallbackAuthorCatalog } from "./authorCatalogFallback";

let lastOk: AuthorCatalog | null = null;

export async function loadAuthorCatalog(): Promise<AuthorCatalog> {
  try {
    lastOk = await rules.authorCatalog();
    return lastOk;
  } catch {
    return lastOk ?? fallbackAuthorCatalog();
  }
}
