/**
 * Maps adapter error codes (already standardized on the backend via
 * `PlatformAdapterError.code`) to a UI severity tone so the account monitor
 * can show colored error badges instead of raw codes.
 *
 * Mapping follows the feasibility plan: red = auth/permission, amber = rate
 * limit / transient, gray = everything else (not_found, contract, capability…).
 */
export type AdapterErrorCodeTone =
  | "neutral"
  | "success"
  | "warning"
  | "danger"
  | "info";

const DANGER_CODES = new Set<string>([
  "authentication_error",
  "permission_denied",
  "adapter_configuration_error",
]);

const WARNING_CODES = new Set<string>([
  "rate_limited",
  "transient_provider_error",
]);

export function adapterErrorCodeTone(
  code: string | null | undefined,
): AdapterErrorCodeTone {
  if (!code) return "neutral";
  if (DANGER_CODES.has(code)) return "danger";
  if (WARNING_CODES.has(code)) return "warning";
  return "neutral";
}
