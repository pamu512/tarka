/**
 * Integration credential calls must not run in production over cleartext HTTP.
 * Relative `/api/ingress/...` fetches inherit the page origin — this guard enforces HTTPS in prod.
 */
export function assertIntegrationSecretsTransportSecure(): void {
  if (typeof window === "undefined") return;
  if (!import.meta.env.PROD) return;
  if (window.location.protocol !== "https:") {
    throw new Error(
      "Integration credentials and API keys must be sent over HTTPS. Serve the UI over TLS (https://) or use a TLS-terminated reverse proxy.",
    );
  }
}
