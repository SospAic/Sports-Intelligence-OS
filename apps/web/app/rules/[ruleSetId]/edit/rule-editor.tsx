"use client";

import type {
  EditorialRule,
  EditorialRuleTree,
  EditorialRuleType,
  ProblemDetails,
} from "@sio/shared-types";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import {
  filterEditorialRules,
  flattenRuleSections,
  splitRuleValues,
} from "@/lib/rule-editor";

const ruleTypes: EditorialRuleType[] = [
  "principle",
  "qualification",
  "research",
  "narrative",
  "language",
  "structure",
  "fact_check",
  "length",
  "output",
  "qa",
  "rewrite",
  "tts",
  "ssml",
  "title",
  "search_keyword",
  "material_search",
];

async function csrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("无法获取 CSRF Token");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function problem(response: Response): Promise<never> {
  const detail = (await response
    .json()
    .catch(() => null)) as ProblemDetails | null;
  throw new Error(detail?.detail ?? `请求失败（${response.status}）`);
}

export function RuleEditor({
  workspaceId,
  ruleSetId,
  tree,
}: {
  workspaceId: string;
  ruleSetId: string;
  tree: EditorialRuleTree;
}) {
  const router = useRouter();
  const sections = useMemo(
    () => flattenRuleSections(tree.sections),
    [tree.sections],
  );
  const allRules = useMemo(
    () => sections.flatMap(({ section }) => section.rules),
    [sections],
  );
  const [rules, setRules] = useState(allRules);
  const [selectedId, setSelectedId] = useState(allRules[0]?.id ?? "");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [mandatoryOnly, setMandatoryOnly] = useState(false);
  const [tag, setTag] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [displayLimit, setDisplayLimit] = useState(120);
  const selected = rules.find((rule) => rule.id === selectedId) ?? null;
  const [draft, setDraft] = useState<EditorialRule | null>(selected);

  const filtered = filterEditorialRules(rules, {
    query,
    type,
    mandatoryOnly,
    tag,
  });
  const visibleRules = filtered.slice(0, displayLimit);

  function choose(rule: EditorialRule) {
    setSelectedId(rule.id);
    setDraft({ ...rule });
    setStatus(null);
  }

  async function save() {
    if (!draft) return;
    setBusy(true);
    setStatus("正在保存草稿…");
    try {
      const response = await fetch(
        `/api/v1/rules/${ruleSetId}/versions/${tree.version.id}/rules/${draft.id}`,
        {
          method: "PATCH",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": await csrf(),
            "X-Workspace-Id": workspaceId,
          },
          body: JSON.stringify({
            title: draft.title,
            rule_type: draft.rule_type,
            instruction: draft.instruction,
            why: draft.why,
            how: draft.how,
            good_example: draft.good_example,
            bad_example: draft.bad_example,
            qa_check: draft.qa_check,
            rewrite_instruction: draft.rewrite_instruction,
            priority: draft.priority,
            severity: draft.severity,
            is_mandatory: draft.is_mandatory,
            enabled: draft.enabled,
            sports: draft.sports,
            story_types: draft.story_types,
            output_types: draft.output_types,
            dependencies: draft.dependencies,
            conflicts: draft.conflicts,
            tags: draft.tags,
            source_status: draft.source_status,
          }),
        },
      );
      if (!response.ok) await problem(response);
      const result = (await response.json()) as {
        version_id: string;
        created_draft: boolean;
        rule: EditorialRule;
      };
      if (result.created_draft) {
        setStatus("已从发布版本创建新草稿并保存，正在切换…");
        router.replace(`/rules/${ruleSetId}/edit?version=${result.version_id}`);
        router.refresh();
      } else {
        setRules((items) =>
          items.map((item) =>
            item.id === result.rule.id ? result.rule : item,
          ),
        );
        setDraft(result.rule);
        setStatus("草稿已保存");
      }
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function batch(enabled: boolean) {
    if (checked.size === 0) return;
    setBusy(true);
    try {
      const response = await fetch(
        `/api/v1/rules/${ruleSetId}/versions/${tree.version.id}/rules`,
        {
          method: "PATCH",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": await csrf(),
            "X-Workspace-Id": workspaceId,
          },
          body: JSON.stringify({
            rule_ids: [...checked],
            changes: { enabled },
          }),
        },
      );
      if (!response.ok) await problem(response);
      const result = (await response.json()) as {
        version_id: string;
        created_draft: boolean;
        updated: number;
      };
      setStatus(`已批量更新 ${result.updated} 条规则`);
      router.replace(`/rules/${ruleSetId}/edit?version=${result.version_id}`);
      router.refresh();
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "批量更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function validateOrPublish(publish: boolean) {
    setBusy(true);
    try {
      const endpoint = publish ? "publish" : "validate";
      const response = await fetch(
        `/api/v1/rules/${ruleSetId}/versions/${tree.version.id}/${endpoint}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": await csrf(),
            "X-Workspace-Id": workspaceId,
          },
          body: JSON.stringify(
            publish ? { reason: "通过可视化编辑器发布" } : {},
          ),
        },
      );
      if (!response.ok) await problem(response);
      const result = (await response.json()) as {
        valid?: boolean;
        errors?: number;
        warnings?: number;
        status?: string;
      };
      setStatus(
        publish
          ? `版本已发布（${result.status}）`
          : `校验完成：${result.errors} 个错误，${result.warnings} 个警告`,
      );
      router.refresh();
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-5 grid min-h-[75vh] gap-4 xl:grid-cols-[320px_minmax(420px,1fr)_380px]">
      <aside className="rounded-2xl border border-slate-800 bg-slate-950/75 p-4">
        <div className="grid gap-2">
          <input
            aria-label="搜索规则"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            onChange={(event) => {
              setQuery(event.target.value);
              setDisplayLimit(120);
            }}
            placeholder="搜索 key、标题或正文"
            value={query}
          />
          <select
            aria-label="规则类型"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            onChange={(event) => {
              setType(event.target.value);
              setDisplayLimit(120);
            }}
            value={type}
          >
            <option value="">全部规则类型</option>
            {ruleTypes.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <input
            aria-label="按标签筛选"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
            onChange={(event) => {
              setTag(event.target.value);
              setDisplayLimit(120);
            }}
            placeholder="标签过滤"
            value={tag}
          />
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input
              checked={mandatoryOnly}
              onChange={(event) => {
                setMandatoryOnly(event.target.checked);
                setDisplayLimit(120);
              }}
              type="checkbox"
            />
            只看强制规则
          </label>
        </div>
        <div className="mt-4 flex gap-2">
          <button
            className="rounded border border-slate-700 px-2 py-1 text-xs"
            onClick={() => batch(true)}
            type="button"
          >
            批量启用
          </button>
          <button
            className="rounded border border-slate-700 px-2 py-1 text-xs"
            onClick={() => batch(false)}
            type="button"
          >
            批量禁用
          </button>
        </div>
        <div className="mt-4 max-h-[58vh] overflow-auto">
          {sections.map(({ section, depth }) => {
            const sectionRules = visibleRules.filter(
              (rule) => rule.section_id === section.id,
            );
            if (sectionRules.length === 0) return null;
            return (
              <details
                className="border-b border-slate-800 py-2"
                key={section.id}
                open={depth === 0}
              >
                <summary
                  className="cursor-pointer text-xs text-slate-400"
                  style={{ paddingLeft: depth * 8 }}
                >
                  {section.title} ({sectionRules.length})
                </summary>
                <div className="mt-2 space-y-1">
                  {sectionRules.map((rule) => (
                    <div className="flex items-start gap-2" key={rule.id}>
                      <input
                        aria-label={`选择规则 ${rule.title}`}
                        checked={checked.has(rule.id)}
                        className="mt-2"
                        onChange={(event) => {
                          const next = new Set(checked);
                          if (event.target.checked) next.add(rule.id);
                          else next.delete(rule.id);
                          setChecked(next);
                        }}
                        type="checkbox"
                      />
                      <button
                        className={`w-full rounded px-2 py-1.5 text-left text-xs ${selectedId === rule.id ? "bg-cyan-950 text-cyan-200" : "text-slate-300 hover:bg-slate-900"}`}
                        onClick={() => choose(rule)}
                        type="button"
                      >
                        <span className="block font-mono text-[10px] text-slate-600">
                          {rule.key}
                        </span>
                        {rule.title}
                      </button>
                    </div>
                  ))}
                </div>
              </details>
            );
          })}
          {visibleRules.length < filtered.length && (
            <button
              className="mt-3 w-full rounded-lg border border-slate-700 px-3 py-2 text-xs text-cyan-300 hover:bg-slate-900"
              onClick={() => setDisplayLimit((value) => value + 120)}
              type="button"
            >
              加载更多（已显示 {visibleRules.length}/{filtered.length}）
            </button>
          )}
        </div>
      </aside>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/75 p-5">
        {draft ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-xs text-cyan-300">
                {draft.key}
              </span>
              <span className="text-xs text-slate-500">
                {draft.source_reference}
              </span>
            </div>
            <label className="block text-xs text-slate-400">
              标题
              <input
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
                onChange={(event) =>
                  setDraft({ ...draft, title: event.target.value })
                }
                value={draft.title}
              />
            </label>
            <label className="block text-xs text-slate-400">
              Instruction
              <textarea
                className="mt-1 min-h-80 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm leading-6 text-slate-200"
                onChange={(event) =>
                  setDraft({ ...draft, instruction: event.target.value })
                }
                value={draft.instruction}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-3">
              <select
                aria-label="规则类型"
                className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-xs"
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    rule_type: event.target.value as EditorialRuleType,
                  })
                }
                value={draft.rule_type}
              >
                {ruleTypes.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
              <input
                aria-label="优先级"
                className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-xs"
                max={100}
                min={0}
                onChange={(event) =>
                  setDraft({ ...draft, priority: Number(event.target.value) })
                }
                type="number"
                value={draft.priority}
              />
              <select
                aria-label="严重级别"
                className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-xs"
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    severity: event.target.value as EditorialRule["severity"],
                  })
                }
                value={draft.severity}
              >
                {(["info", "warning", "error", "critical"] as const).map(
                  (item) => (
                    <option key={item}>{item}</option>
                  ),
                )}
              </select>
            </div>
            <div className="flex gap-5 text-sm text-slate-300">
              <label>
                <input
                  aria-label="启用规则"
                  checked={draft.enabled}
                  onChange={(event) =>
                    setDraft({ ...draft, enabled: event.target.checked })
                  }
                  type="checkbox"
                />{" "}
                启用
              </label>
              <label>
                <input
                  aria-label="设为强制规则"
                  checked={draft.is_mandatory}
                  onChange={(event) =>
                    setDraft({ ...draft, is_mandatory: event.target.checked })
                  }
                  type="checkbox"
                />{" "}
                强制
              </label>
            </div>
            <button
              className="rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
              disabled={busy}
              onClick={save}
              type="button"
            >
              {busy ? "处理中…" : "保存草稿"}
            </button>
          </div>
        ) : (
          <p className="text-sm text-slate-400">没有符合筛选条件的规则。</p>
        )}
      </div>

      <aside className="rounded-2xl border border-slate-800 bg-slate-950/75 p-5">
        {draft ? (
          <div className="space-y-4">
            {(
              [
                "why",
                "how",
                "good_example",
                "bad_example",
                "qa_check",
                "rewrite_instruction",
              ] as const
            ).map((field) => (
              <label className="block text-xs text-slate-400" key={field}>
                {field}
                <textarea
                  className="mt-1 min-h-20 w-full rounded-lg border border-slate-700 bg-slate-900 p-2 text-xs text-slate-200"
                  onChange={(event) =>
                    setDraft({ ...draft, [field]: event.target.value || null })
                  }
                  value={draft[field] ?? ""}
                />
              </label>
            ))}
            {(
              [
                "tags",
                "sports",
                "story_types",
                "output_types",
                "dependencies",
                "conflicts",
              ] as const
            ).map((field) => (
              <label className="block text-xs text-slate-400" key={field}>
                {field}（逗号分隔）
                <input
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-xs"
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      [field]: splitRuleValues(event.target.value),
                    })
                  }
                  value={draft[field].join(", ")}
                />
              </label>
            ))}
          </div>
        ) : null}
        <div className="mt-6 flex flex-wrap gap-2 border-t border-slate-800 pt-5">
          <button
            className="rounded border border-slate-700 px-3 py-2 text-xs text-slate-200"
            disabled={busy}
            onClick={() => validateOrPublish(false)}
            type="button"
          >
            运行校验
          </button>
          <button
            className="rounded border border-emerald-800 px-3 py-2 text-xs text-emerald-200"
            disabled={busy || tree.version.status !== "draft"}
            onClick={() => validateOrPublish(true)}
            type="button"
          >
            发布版本
          </button>
        </div>
        {status ? (
          <p className="mt-4 rounded-lg border border-slate-700 bg-slate-900 p-3 text-xs text-slate-200">
            {status}
          </p>
        ) : null}
      </aside>
    </section>
  );
}
