type AccountLabelInput = {
  display_name?: string | null;
  username?: string | null;
  external_id?: string | null;
  platform_name?: string | null;
};

const LEGACY_PLACEHOLDER_NAMES = new Set(["的抖音", "undefined", "null"]);

/** Keep account labels readable when old records contain a profile URL or placeholder. */
export function accountDisplayName(account: AccountLabelInput): string {
  const displayName = account.display_name?.trim() ?? "";
  const candidates = [displayName, account.username?.trim() ?? ""];
  for (const candidate of candidates) {
    if (!candidate || LEGACY_PLACEHOLDER_NAMES.has(candidate.toLowerCase())) {
      continue;
    }
    const urlCandidate = candidate.replace(/^@(?=https?:\/\/)/i, "");
    if (/^https?:\/\//i.test(urlCandidate)) {
      try {
        const url = new URL(urlCandidate);
        const parts = url.pathname.split("/").filter(Boolean);
        const handle = parts.at(-1)?.replace(/^@/, "");
        if (handle) return "@" + handle;
      } catch {
        // Continue to the external id fallback.
      }
      continue;
    }
    return candidate;
  }

  const externalId = account.external_id?.trim() ?? "";
  if (externalId) {
    return account.platform_name
      ? account.platform_name + "账号 · " + externalId
      : externalId;
  }
  return "未命名账号";
}
