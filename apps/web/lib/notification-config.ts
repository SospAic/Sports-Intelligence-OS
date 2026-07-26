export function normalizeNotificationConfig(
  config: Record<string, string | boolean>,
): Record<string, unknown> {
  const normalized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(config)) {
    if (key === "port") normalized[key] = Number(value);
    else if (key === "to_emails") {
      normalized[key] = String(value)
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    } else if (key === "headers") {
      normalized[key] = value ? JSON.parse(String(value)) : {};
    } else normalized[key] = value;
  }
  return normalized;
}
