export type EvidenceWindow = {
  startMs: number;
  endMs: number;
  label: string;
  sourceRef?: string;
};

export function formatEvidenceTime(valueMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(valueMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return String(hours) + ":" + String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
  }
  return String(minutes) + ":" + String(seconds).padStart(2, "0");
}

export function evidenceWindowFromMs(
  startMs: number | null | undefined,
  endMs: number | null | undefined,
  label: string,
  sourceRef?: string | null,
): EvidenceWindow | undefined {
  if (
    startMs == null ||
    endMs == null ||
    !Number.isFinite(startMs) ||
    !Number.isFinite(endMs) ||
    startMs < 0 ||
    endMs <= startMs
  ) {
    return undefined;
  }
  return { startMs, endMs, label, ...(sourceRef ? { sourceRef } : {}) };
}

export function evidenceLocatorUrl(url: string, startMs: number): string {
  const seconds = Math.max(0, Math.floor(startMs / 1000));
  try {
    const parsed = new URL(url);
    if (parsed.hostname === "youtu.be" || parsed.hostname.endsWith("youtube.com")) {
      parsed.searchParams.set("t", String(seconds) + "s");
    } else {
      parsed.hash = "t=" + seconds;
    }
    return parsed.toString();
  } catch {
    return url + "#t=" + seconds;
  }
}
