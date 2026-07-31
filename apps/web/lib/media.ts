export function normalizeExternalImageUrl(
  value: string | null | undefined,
): string | null {
  if (!value) return null;

  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;

    if (
      url.protocol === "http:" &&
      (url.hostname === "hdslb.com" || url.hostname.endsWith(".hdslb.com"))
    ) {
      url.protocol = "https:";
    }
    return url.toString();
  } catch {
    return null;
  }
}
