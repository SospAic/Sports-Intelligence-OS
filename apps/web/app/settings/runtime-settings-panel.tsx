"use client";

import type {
  RuntimeSettingField,
  RuntimeSettingsRecord,
} from "@sio/shared-types";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCopy, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  SettingsGroup,
  SkeletonRows,
  StatePanel,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

const COMPOSITE_ENV_VARS = new Set(["SIO_DATABASE_URL", "SIO_REDIS_URL"]);

function serializeEnvValue(value: RuntimeSettingField["value"]): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  return value === null ? "" : String(value);
}

export function RuntimeSettingsPanel({
  sectionKeys,
}: {
  sectionKeys?: string[];
} = {}) {
  const { workspaceId } = useWorkspace();
  const { notify } = useToast();
  const runtime = useQuery({
    queryKey: ["runtime-settings", workspaceId],
    queryFn: () =>
      apiRequest<RuntimeSettingsRecord>("/settings/runtime", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const [overrides, setOverrides] = useState<Record<string, string | boolean>>(
    {},
  );
  const sections = useMemo(() => {
    const all = runtime.data?.sections ?? [];
    return sectionKeys
      ? all.filter((section) => sectionKeys.includes(section.key))
      : all;
  }, [runtime.data, sectionKeys]);

  const envDraft = useMemo(() => {
    const initial: Record<string, string | boolean> = {};
    for (const section of sections) {
      for (const field of section.fields) {
        if (field.secret || COMPOSITE_ENV_VARS.has(field.env_var)) continue;
        initial[field.env_var] =
          typeof field.value === "boolean"
            ? field.value
            : serializeEnvValue(field.value);
      }
    }
    return Object.entries({ ...initial, ...overrides })
      .sort(([left], [right]) => left.localeCompare(right))
      .map(
        ([key, value]) =>
          `${key}=${typeof value === "boolean" ? String(value) : value}`,
      )
      .join("\n");
  }, [overrides, sections]);

  async function copyDraft() {
    try {
      await navigator.clipboard.writeText(envDraft);
      notify(
        "环境变量草稿已复制；写入 .env 或 Secret 后需重启 API、Worker 与 Beat。",
        "success",
      );
    } catch {
      notify("浏览器未允许写入剪贴板，请手动复制下方内容。", "error");
    }
  }

  if (runtime.isLoading) return <SkeletonRows count={7} />;
  if (runtime.error) {
    return (
      <StatePanel
        type="error"
        title="无法读取运行参数"
        detail={runtime.error.message}
        onRetry={() => runtime.refetch()}
      />
    );
  }
  if (!runtime.data) return <StatePanel type="empty" title="暂无运行参数" />;

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-amber-900/70 bg-amber-950/20 p-4 text-sm leading-6 text-amber-100">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="warning">{runtime.data.environment}</Badge>
          <span>部署级参数 · 重启后生效</span>
        </div>
        <p className="mt-2 text-xs text-amber-200/80">{runtime.data.warning}</p>
      </div>

      {sections.map((section) => (
        <Panel key={section.key} className="overflow-hidden p-0">
          <SettingsGroup
            title={section.title}
            description={section.description}
            tone="slate"
            className="m-5"
          >
          <div className="grid gap-3 lg:grid-cols-2">
            {section.fields.map((field) => {
              const composite = COMPOSITE_ENV_VARS.has(field.env_var);
              const editable = !field.secret && !composite;
              return (
                <label
                  className="grid min-w-0 gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm"
                  key={field.key}
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="text-slate-200">{field.label}</span>
                    <code className="text-[10px] text-slate-500">
                      {field.env_var}
                    </code>
                  </span>
                  {field.secret ? (
                    <div className="flex h-10 items-center rounded-lg border border-slate-800 bg-slate-900/60 px-3">
                      <Badge tone={field.value ? "success" : "warning"}>
                        {field.value ? "已配置（内容不回传）" : "未配置"}
                      </Badge>
                    </div>
                  ) : field.value_type === "boolean" && editable ? (
                    <span className="flex h-10 items-center gap-3 rounded-lg border border-slate-700 bg-slate-950 px-3">
                      <input
                        checked={Boolean(
                          overrides[field.env_var] ?? field.value,
                        )}
                        onChange={(event) =>
                          setOverrides((value) => ({
                            ...value,
                            [field.env_var]: event.target.checked,
                          }))
                        }
                        type="checkbox"
                      />
                      {(overrides[field.env_var] ?? field.value)
                        ? "启用"
                        : "停用"}
                    </span>
                  ) : (
                    <input
                      className={inputClass}
                      disabled={!editable}
                      max={field.maximum ?? undefined}
                      min={field.minimum ?? undefined}
                      onChange={(event) =>
                        setOverrides((value) => ({
                          ...value,
                          [field.env_var]: event.target.value,
                        }))
                      }
                      type={field.value_type === "number" ? "number" : "text"}
                      value={
                        editable
                          ? String(
                              overrides[field.env_var] ?? field.value ?? "",
                            )
                          : serializeEnvValue(field.value)
                      }
                    />
                  )}
                  <span className="text-xs leading-5 text-slate-500">
                    {field.description}
                    {composite
                      ? " 该值属于含凭证的复合 URL，只脱敏展示；请在部署 Secret 中修改完整 URL。"
                      : ""}
                  </span>
                </label>
              );
            })}
          </div>
          </SettingsGroup>
        </Panel>
      ))}

      <Panel className="p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="font-medium text-white">可复制的环境变量草稿</h2>
            <p className="mt-1 text-xs text-slate-500">
              不包含数据库/Redis
              URL、密码或加密密钥。页面修改只影响这份草稿，不会改写服务器文件。
            </p>
          </div>
          <div className="flex gap-2">
            <button
              className={secondaryButtonClass}
              onClick={() => {
                setOverrides({});
                void runtime.refetch();
              }}
              type="button"
            >
              <RotateCcw size={14} />
              恢复当前值
            </button>
            <button
              className={secondaryButtonClass}
              disabled={!envDraft}
              onClick={copyDraft}
              type="button"
            >
              <ClipboardCopy size={14} />
              复制草稿
            </button>
          </div>
        </div>
        <pre className="mt-4 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-300">
          {envDraft}
        </pre>
      </Panel>
    </div>
  );
}
