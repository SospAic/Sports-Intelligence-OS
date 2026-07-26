"use client";
import type {
  AutomationActionRecord,
  AutomationEvaluationPage,
  AutomationRuleDetail,
  GenerationWorkflow,
  NotificationChannelRecord,
} from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Braces, Plus, Save, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  PageHeader,
  Panel,
  SkeletonRows,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";
import { formatDate } from "@/lib/format";
export type EntityType = "content" | "account" | "news" | "topic_event";
export type Leaf = {
  id: string;
  kind: "leaf";
  field: string;
  operator: string;
  value: string;
};
export type Group = {
  id: string;
  kind: "group";
  operator: "AND" | "OR" | "NOT";
  conditions: Node[];
};
export type Node = Leaf | Group;
type Action = {
  id: string;
  action_type: string;
  channel_id?: string;
  workflow_id?: string;
  title?: string;
  body?: string;
};
const fields: Record<EntityType, string[]> = {
  content: [
    "entity_id",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
    "favorite_count",
    "view_growth_1h",
    "view_growth_6h",
    "view_growth_24h",
    "engagement_rate",
    "share_rate",
    "favorite_rate",
    "view_velocity",
    "view_acceleration",
    "viral_score",
    "source_kind",
    "platform_key",
    "title",
  ],
  account: [
    "entity_id",
    "follower_count",
    "following_count",
    "total_like_count",
    "total_view_count",
    "video_count",
    "follower_growth_24h",
    "engagement_rate",
    "source_kind",
    "platform_key",
  ],
  news: [
    "entity_id",
    "heat_score",
    "source_count",
    "article_count",
    "reliability_score",
    "controversy_score",
    "visual_score",
    "story_score",
    "sport",
    "league",
    "status",
    "source_kind",
  ],
  topic_event: [
    "entity_id",
    "heat_score",
    "source_count",
    "article_count",
    "reliability_score",
    "controversy_score",
    "visual_score",
    "story_score",
    "sport",
    "league",
    "status",
    "source_kind",
  ],
};
const operators = [
  "eq",
  "ne",
  "gt",
  "gte",
  "lt",
  "lte",
  "in",
  "not_in",
  "contains",
  "not_contains",
  "regex",
  "changed",
  "increased_by",
  "increased_percent",
  "consecutive_matches",
];
const uid = () => Math.random().toString(36).slice(2);
const leaf = (entity: EntityType): Leaf => ({
  id: uid(),
  kind: "leaf",
  field: fields[entity][0]!,
  operator: "gte",
  value: "1000000",
});
function parseNode(value: Record<string, unknown>): Node {
  const operator = String(value.operator);
  if (["AND", "OR", "NOT"].includes(operator))
    return {
      id: uid(),
      kind: "group",
      operator: operator as Group["operator"],
      conditions: ((value.conditions as Record<string, unknown>[]) ?? []).map(
        parseNode,
      ),
    };
  return {
    id: uid(),
    kind: "leaf",
    field: String(value.field),
    operator,
    value: Array.isArray(value.value)
      ? value.value.join(", ")
      : value.value === undefined
        ? ""
        : String(value.value),
  };
}
function parseRoot(value: Record<string, unknown>): Group {
  const parsed = parseNode(value);
  return parsed.kind === "group"
    ? parsed
    : { id: uid(), kind: "group", operator: "AND", conditions: [parsed] };
}
export function serializeConditionNode(node: Node): Record<string, unknown> {
  if (node.kind === "group")
    return {
      operator: node.operator,
      conditions: node.conditions.map(serializeConditionNode),
    };
  let value: unknown = node.value;
  if (["in", "not_in"].includes(node.operator))
    value = node.value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  else if (
    !["contains", "not_contains", "regex", "eq", "ne"].includes(
      node.operator,
    ) ||
    /^-?\d+(\.\d+)?$/.test(node.value)
  )
    value = Number(node.value);
  const result: Record<string, unknown> = {
    field: node.field,
    operator: node.operator,
  };
  if (node.operator !== "changed") result.value = value;
  return result;
}
function configToAction(action: AutomationActionRecord): Action {
  return {
    id: action.id,
    action_type: action.action_type,
    channel_id: String(action.config.channel_id ?? ""),
    workflow_id: String(action.config.workflow_id ?? ""),
    title: String(action.config.title ?? ""),
    body: String(action.config.body ?? ""),
  };
}
export function AutomationEditor({ id }: { id?: string }) {
  const { workspaceId } = useWorkspace();
  const detail = useQuery({
    queryKey: ["automation", id],
    queryFn: () =>
      apiRequest<AutomationRuleDetail>(`/automations/${id}`, {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId && id),
  });
  if (id && detail.isLoading)
    return (
      <main className="p-8">
        <SkeletonRows />
      </main>
    );
  if (id && detail.error)
    return (
      <main className="p-8">
        <StatePanel
          type="error"
          title="自动化加载失败"
          detail={detail.error.message}
        />
      </main>
    );
  return <AutomationEditorForm id={id} initial={detail.data} />;
}

function AutomationEditorForm({
  id,
  initial,
}: {
  id?: string;
  initial?: AutomationRuleDetail;
}) {
  const { workspaceId, role } = useWorkspace();
  const searchParams = useSearchParams();
  const { notify } = useToast();
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const requestedEntity = searchParams.get("entity") as EntityType | null;
  const initialEntity =
    initial?.entity_type ??
    (requestedEntity && fields[requestedEntity] ? requestedEntity : "content");
  const requestedIds =
    searchParams.get("ids")?.split(",").filter(Boolean) ?? [];
  const [entityType, setEntityType] = useState<EntityType>(initialEntity);
  const [root, setRoot] = useState<Group>(() =>
    initial
      ? parseRoot(initial.condition_tree)
      : requestedIds.length
        ? {
            id: uid(),
            kind: "group",
            operator: "AND",
            conditions: [
              {
                id: uid(),
                kind: "leaf",
                field: "entity_id",
                operator: "in",
                value: requestedIds.join(", "),
              },
              leaf(initialEntity),
            ],
          }
        : {
            id: uid(),
            kind: "group",
            operator: "AND",
            conditions: [leaf(initialEntity)],
          },
  );
  const [actions, setActions] = useState<Action[]>(
    () => initial?.actions.map(configToAction) ?? [],
  );
  const [cooldown, setCooldown] = useState(initial?.cooldown_seconds ?? 3600);
  const [dedup, setDedup] = useState(initial?.deduplication_window ?? 3600);
  const [enabled, setEnabled] = useState(initial?.enabled ?? false);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState("");
  const [saving, setSaving] = useState(false);
  const channels = useQuery({
    queryKey: ["notification-channels", workspaceId],
    queryFn: () =>
      apiRequest<NotificationChannelRecord[]>("/notification-channels", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const workflows = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () =>
      apiRequest<GenerationWorkflow[]>("/workflows", {
        workspaceId: workspaceId!,
      }),
    enabled: Boolean(workspaceId),
  });
  const evaluations = useQuery({
    queryKey: ["automation-evaluations", id],
    queryFn: () =>
      apiRequest<AutomationEvaluationPage>(
        `/automation-evaluations?page=1&page_size=20&rule_id=${id}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId && id),
  });
  function toggleJsonMode() {
    if (!jsonMode)
      setJsonText(JSON.stringify(serializeConditionNode(root), null, 2));
    setJsonMode(!jsonMode);
  }
  function updateNode(target: string, updater: (node: Node) => Node) {
    const walk = (node: Node): Node =>
      node.id === target
        ? updater(node)
        : node.kind === "group"
          ? { ...node, conditions: node.conditions.map(walk) }
          : node;
    setRoot(walk(root) as Group);
  }
  function removeNode(target: string) {
    const walk = (group: Group): Group => ({
      ...group,
      conditions: group.conditions
        .filter((n) => n.id !== target)
        .map((n) => (n.kind === "group" ? walk(n) : n)),
    });
    setRoot(walk(root));
  }
  function changeEntity(next: EntityType) {
    setEntityType(next);
    setRoot({
      id: uid(),
      kind: "group",
      operator: "AND",
      conditions: [leaf(next)],
    });
  }
  const tree = useMemo(() => serializeConditionNode(root), [root]);
  async function save() {
    if (!workspaceId) return;
    setSaving(true);
    try {
      const finalTree = jsonMode
        ? (JSON.parse(jsonText) as Record<string, unknown>)
        : tree;
      await apiRequest("/automations/validate", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          entity_type: entityType,
          condition_tree: finalTree,
        }),
      });
      const payload = {
        name,
        description: description || null,
        entity_type: entityType,
        trigger_type: "entity_updated",
        condition_tree: finalTree,
        schedule: {},
        cooldown_seconds: cooldown,
        deduplication_window: dedup,
        enabled,
        priority: 100,
        actions: id
          ? undefined
          : actions.map((action, index) => actionPayload(action, index)),
      };
      if (id) {
        await apiRequest(`/automations/${id}`, {
          method: "PATCH",
          workspaceId,
          csrf: true,
          body: JSON.stringify({
            name,
            description: description || null,
            condition_tree: finalTree,
            schedule: {},
            cooldown_seconds: cooldown,
            deduplication_window: dedup,
            enabled,
            priority: 100,
          }),
        });
        for (const old of initial?.actions ?? [])
          await apiRequest(`/automations/${id}/actions/${old.id}`, {
            method: "DELETE",
            workspaceId,
            csrf: true,
          });
        for (const [index, action] of actions.entries())
          await apiRequest(`/automations/${id}/actions`, {
            method: "POST",
            workspaceId,
            csrf: true,
            body: JSON.stringify(actionPayload(action, index)),
          });
        notify("自动化规则已保存");
        await qc.invalidateQueries({ queryKey: ["automation", id] });
      } else {
        const created = await apiRequest<AutomationRuleDetail>("/automations", {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify(payload),
        });
        notify("自动化规则已创建");
        router.replace(`/automations/${created.id}`);
      }
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    } finally {
      setSaving(false);
    }
  }
  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Visual Rule Builder"
        title={id ? "编辑自动化" : "新建自动化"}
        description="普通模式无需手写 JSON；条件会在保存前由后端使用同一 DSL 校验。"
        actions={
          <>
            <button className={secondaryButtonClass} onClick={toggleJsonMode}>
              <Braces size={15} />
              {jsonMode ? "返回可视化" : "JSON 视图"}
            </button>
            <button
              className={buttonClass}
              disabled={
                saving || !["owner", "admin", "editor"].includes(role ?? "")
              }
              onClick={save}
            >
              <Save size={15} />
              {saving ? "保存中…" : "保存"}
            </button>
          </>
        }
      />
      <div className="grid gap-5 xl:grid-cols-[1fr_2fr]">
        <Panel className="space-y-4 p-5">
          <label className="grid gap-2 text-sm">
            名称
            <input
              className={inputClass}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：百万播放提醒"
            />
          </label>
          <label className="grid gap-2 text-sm">
            说明
            <textarea
              className={`${inputClass} h-24 py-2`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label className="grid gap-2 text-sm">
            监控实体
            <select
              className={inputClass}
              value={entityType}
              onChange={(e) => changeEntity(e.target.value as EntityType)}
              disabled={Boolean(id)}
            >
              <option value="content">作品</option>
              <option value="account">账号</option>
              <option value="news">新闻</option>
              <option value="topic_event">热点事件</option>
            </select>
          </label>
          <label className="grid gap-2 text-sm">
            冷却时间（秒）
            <input
              className={inputClass}
              type="number"
              min="0"
              value={cooldown}
              onChange={(e) => setCooldown(Number(e.target.value))}
            />
          </label>
          <label className="grid gap-2 text-sm">
            去重窗口（秒）
            <input
              className={inputClass}
              type="number"
              min="0"
              value={dedup}
              onChange={(e) => setDedup(Number(e.target.value))}
            />
          </label>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            启用规则
          </label>
        </Panel>
        <div className="space-y-5">
          <Panel className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="font-medium text-white">触发条件</h2>
                <p className="mt-1 text-xs text-slate-500">
                  支持嵌套 AND / OR / NOT
                </p>
              </div>
            </div>
            {jsonMode ? (
              <textarea
                className="min-h-96 w-full rounded-xl border border-slate-700 bg-slate-950 p-4 font-mono text-xs text-slate-300"
                value={jsonText}
                onChange={(e) => setJsonText(e.target.value)}
              />
            ) : (
              <ConditionGroup
                node={root}
                entity={entityType}
                onUpdate={updateNode}
                onRemove={removeNode}
                root
              />
            )}
          </Panel>
          <Panel className="p-5">
            <div className="flex items-center justify-between">
              <h2 className="font-medium text-white">执行动作</h2>
              <button
                className={secondaryButtonClass}
                onClick={() =>
                  setActions((items) => [
                    ...items,
                    { id: uid(), action_type: "notification" },
                  ])
                }
              >
                <Plus size={14} />
                添加动作
              </button>
            </div>
            <div className="mt-4 space-y-3">
              {actions.map((action, index) => (
                <div
                  className="grid gap-3 rounded-xl border border-slate-800 p-4 md:grid-cols-[2rem_1fr_1fr_auto]"
                  key={action.id}
                >
                  <span className="grid size-8 place-items-center rounded-full bg-slate-800 text-xs">
                    {index + 1}
                  </span>
                  <select
                    className={inputClass}
                    value={action.action_type}
                    onChange={(e) =>
                      setActions((items) =>
                        items.map((item) =>
                          item.id === action.id
                            ? { id: item.id, action_type: e.target.value }
                            : item,
                        ),
                      )
                    }
                  >
                    <option value="notification">发送通知</option>
                    <option value="create_topic">创建选题</option>
                    <option value="create_generation">调用生成工作流</option>
                    <option value="save_content">保存作品</option>
                    <option value="webhook">Webhook</option>
                    <option value="external_api">外部 API 渠道</option>
                  </select>
                  {["notification", "webhook", "external_api"].includes(
                    action.action_type,
                  ) ? (
                    <select
                      className={inputClass}
                      value={action.channel_id ?? ""}
                      onChange={(e) =>
                        setActions((items) =>
                          items.map((item) =>
                            item.id === action.id
                              ? { ...item, channel_id: e.target.value }
                              : item,
                          ),
                        )
                      }
                    >
                      <option value="">选择通知渠道</option>
                      {channels.data?.map((channel) => (
                        <option key={channel.id} value={channel.id}>
                          {channel.name}
                        </option>
                      ))}
                    </select>
                  ) : action.action_type === "create_generation" ? (
                    <select
                      className={inputClass}
                      value={action.workflow_id ?? ""}
                      onChange={(e) =>
                        setActions((items) =>
                          items.map((item) =>
                            item.id === action.id
                              ? { ...item, workflow_id: e.target.value }
                              : item,
                          ),
                        )
                      }
                    >
                      <option value="">选择工作流</option>
                      {workflows.data?.map((workflow) => (
                        <option key={workflow.id} value={workflow.id}>
                          {workflow.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="grid place-items-center text-xs text-slate-500">
                      无需额外配置
                    </div>
                  )}
                  <button
                    className="text-rose-300"
                    onClick={() =>
                      setActions((items) =>
                        items.filter((item) => item.id !== action.id),
                      )
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
      {id && (
        <Panel>
          <div className="border-b border-slate-800 p-5">
            <h2 className="font-medium text-white">执行历史</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {evaluations.data?.items.map((item) => (
              <div
                className="grid gap-2 p-4 text-sm md:grid-cols-4"
                key={item.id}
              >
                <span>{formatDate(item.evaluated_at)}</span>
                <Badge tone={item.matched ? "success" : "neutral"}>
                  {item.matched ? "已匹配" : "未匹配"}
                </Badge>
                <span>{item.execution_status}</span>
                <span className="truncate text-xs text-slate-500">
                  {item.event_key}
                </span>
              </div>
            ))}
          </div>
          {!evaluations.data?.items.length && (
            <StatePanel type="empty" title="暂无执行历史" />
          )}
        </Panel>
      )}
    </main>
  );
}
function actionPayload(action: Action, index: number) {
  const config: Record<string, unknown> = {};
  if (action.channel_id) config.channel_id = action.channel_id;
  if (action.workflow_id) config.workflow_id = action.workflow_id;
  if (action.title) config.title = action.title;
  if (action.body) config.body = action.body;
  return {
    action_type: action.action_type,
    config,
    sort_order: index,
    enabled: true,
  };
}
function ConditionGroup({
  node,
  entity,
  onUpdate,
  onRemove,
  root = false,
}: {
  node: Group;
  entity: EntityType;
  onUpdate: (id: string, updater: (node: Node) => Node) => void;
  onRemove: (id: string) => void;
  root?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/30 p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">满足</span>
        <select
          className={`${inputClass} h-8`}
          value={node.operator}
          onChange={(e) =>
            onUpdate(
              node.id,
              (current) =>
                ({
                  ...current,
                  operator: e.target.value as Group["operator"],
                }) as Group,
            )
          }
        >
          <option value="AND">全部条件（AND）</option>
          <option value="OR">任一条件（OR）</option>
          <option value="NOT">条件不成立（NOT）</option>
        </select>
        <button
          className={`${secondaryButtonClass} h-8 px-2`}
          disabled={node.operator === "NOT" && node.conditions.length >= 1}
          onClick={() =>
            onUpdate(node.id, (current) => ({
              ...current,
              conditions: [...(current as Group).conditions, leaf(entity)],
            }))
          }
        >
          <Plus size={13} />
          条件
        </button>
        <button
          className={`${secondaryButtonClass} h-8 px-2`}
          disabled={node.operator === "NOT" && node.conditions.length >= 1}
          onClick={() =>
            onUpdate(node.id, (current) => ({
              ...current,
              conditions: [
                ...(current as Group).conditions,
                {
                  id: uid(),
                  kind: "group",
                  operator: "AND",
                  conditions: [leaf(entity)],
                },
              ],
            }))
          }
        >
          <Plus size={13} />
          条件组
        </button>
        {!root && (
          <button
            className="ml-auto text-rose-300"
            onClick={() => onRemove(node.id)}
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>
      <div className="space-y-2">
        {node.conditions.map((child) =>
          child.kind === "group" ? (
            <ConditionGroup
              key={child.id}
              node={child}
              entity={entity}
              onUpdate={onUpdate}
              onRemove={onRemove}
            />
          ) : (
            <div
              className="grid gap-2 rounded-lg border border-slate-800 bg-slate-950/50 p-2 md:grid-cols-[1fr_1fr_1fr_auto]"
              key={child.id}
            >
              <select
                className={`${inputClass} h-9`}
                value={child.field}
                onChange={(e) =>
                  onUpdate(
                    child.id,
                    (current) =>
                      ({ ...current, field: e.target.value }) as Leaf,
                  )
                }
              >
                {fields[entity].map((field) => (
                  <option key={field} value={field}>
                    {field}
                  </option>
                ))}
              </select>
              <select
                className={`${inputClass} h-9`}
                value={child.operator}
                onChange={(e) =>
                  onUpdate(
                    child.id,
                    (current) =>
                      ({ ...current, operator: e.target.value }) as Leaf,
                  )
                }
              >
                {operators.map((operator) => (
                  <option key={operator} value={operator}>
                    {operator}
                  </option>
                ))}
              </select>
              <input
                className={`${inputClass} h-9`}
                disabled={child.operator === "changed"}
                value={child.value}
                onChange={(e) =>
                  onUpdate(
                    child.id,
                    (current) =>
                      ({ ...current, value: e.target.value }) as Leaf,
                  )
                }
                placeholder={
                  ["in", "not_in"].includes(child.operator)
                    ? "逗号分隔"
                    : "比较值"
                }
              />
              <button
                className="text-rose-300"
                onClick={() => onRemove(child.id)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ),
        )}
      </div>
    </div>
  );
}
