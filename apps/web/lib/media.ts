export function normalizeExternalImageUrl(
  value: string | null | undefined,
): string | null {
  if (!value) return null;

  // Locally-archived media is served from our own origin under
  // /api/v1/media/... (a same-origin path, not an external http(s) URL). It
  // must bypass the external-URL checks below so the <img> can load a stable,
  // expiry-proof thumbnail instead of a platform's signed CDN link that 404s
  // hours later. The media route itself enforces auth + workspace ownership +
  // an allow-list of recorded filenames, so this passthrough is safe.
  if (value.startsWith("/api/v1/media/")) return value;

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

/** Minimal shape needed to resolve a content item's best cover image. */
export interface ContentCoverSource {
  id: string;
  cover_url: string | null;
  media: { thumbnail?: string | null } | null;
}

/** Resolve the best cover image for a content item.
 *
 * Prefers the locally-archived thumbnail (stable, never expires) when present,
 * and falls back to the platform-provided external cover URL — which for
 * TikTok / Douyin is a short-lived signed CDN link that 404s by the time the
 * page is opened. Returns null when neither is available. Pair the result with
 * <ExternalImage> so a broken or expired URL still degrades gracefully.
 */
export function contentCoverUrl(
  content: ContentCoverSource | null | undefined,
): string | null {
  if (!content) return null;
  const thumb = content.media?.thumbnail;
  if (thumb) return `/api/v1/media/${content.id}/${thumb}`;
  return normalizeExternalImageUrl(content.cover_url);
}
