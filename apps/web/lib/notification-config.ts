import type { ConfigFieldDescriptor } from "@sio/shared-types";

export type NotificationConfigInput = Record<string, string | number | boolean>;

export function normalizeNotificationConfig(
  config: NotificationConfigInput,
  fields: ConfigFieldDescriptor[] = [],
): Record<string, unknown> {
  const normalized: Record<string, unknown> = {};
  const descriptors = new Map(fields.map((field) => [field.key, field]));
  for (const [key, value] of Object.entries(config)) {
    const field = descriptors.get(key);
    if (value === "" && field?.secret) continue;
    if (field?.value_type === "number" || key === "port") {
      if (value !== "") normalized[key] = Number(value);
    } else if (field?.value_type === "list" || key === "to_emails") {
      normalized[key] = String(value)
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean);
    } else if (field?.value_type === "json" || key === "headers") {
      normalized[key] = value ? JSON.parse(String(value)) : {};
    } else normalized[key] = value;
  }
  return normalized;
}

export function notificationConfigDefaults(
  fields: ConfigFieldDescriptor[],
): NotificationConfigInput {
  const values: NotificationConfigInput = {};
  for (const field of fields) {
    if (field.default === null || field.default === undefined) continue;
    if (field.value_type === "json") {
      values[field.key] = JSON.stringify(field.default, null, 2);
    } else if (field.value_type === "list" && Array.isArray(field.default)) {
      values[field.key] = field.default.join("\n");
    } else if (["string", "number", "boolean"].includes(typeof field.default)) {
      values[field.key] = field.default as string | number | boolean;
    }
  }
  return values;
}
