"use client";

import type {
  EditorialItem,
  EditorialItemPage,
  EditorialMember,
  EditorialSavedView,
  EditorialStatus,
} from "@sio/shared-types";
import {
  Check,
  CheckSquare,
  ClipboardCheck,
  Clock3,
  Filter,
  RotateCcw,
  Save,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useWorkspace } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

const statusLabels: Record<EditorialStatus, string> = {
  draft: "草稿",
  in_review: "待审核",
  approved: "已批准",
  rejected: "已退回",
  archived: "已归档",
};

const statusTones: Record<EditorialStatus, "neutral" | "warning" | "success" | "danger"> = {
  draft: "neutral",
  in_review: "warning",
  approved: "success",
  rejected: "danger",
  archived: "neutral",
};

type Filter = "all" | EditorialStatus | "overdue";
const filters: Filter[] = ["all", "draft", "in_review", "approved", "rejected", "overdue"];

export function EditorialClient() {
  const { workspaceId, role, currentUser } = useWorkspace();
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [assigneeFilter, setAssigneeFilter] = useState("");
  const [priorityMin, setPriorityMin] = useState("");
  const [priorityMax, setPriorityMax] = useState("");
  const [selectedViewId, setSelectedViewId] = useState("");
  const [viewName, setViewName] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkStatus, setBulkStatus] = useState<EditorialStatus | "">("");
  const [bulkAssignee, setBulkAssignee] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const canReview = ["owner", "admin", "editor"].includes(role ?? "");
  const canEdit = ["owner", "admin", "editor", "analyst"].includes(role ?? "");
  const canManageViews = ["owner", "admin"].includes(role ?? "");

  const membersQuery = useQuery({
    queryKey: ["editorial-members", workspaceId],
    queryFn: () => apiRequest<EditorialMember[]>("/workspace-members", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
  });
  const viewsQuery = useQuery({
    queryKey: ["editorial-views", workspaceId],
    queryFn: () => apiRequest<EditorialSavedView[]>("/editorial-views", { workspaceId: workspaceId! }),
    enabled: Boolean(workspaceId),
  });
  const query = useQuery({
    queryKey: ["editorial-items", workspaceId, filter, assigneeFilter, priorityMin, priorityMax],
    queryFn: () => {
      const params = new URLSearchParams({ page: "1", page_size: "100" });
      if (filter === "overdue") params.set("overdue", "true");
      else if (filter !== "all") params.set("status", filter);
      if (assigneeFilter === "__none__") params.set("unassigned", "true");
      else if (assigneeFilter) params.set("assignee_id", assigneeFilter);
      if (priorityMin) params.set("priority_min", priorityMin);
      if (priorityMax) params.set("priority_max", priorityMax);
      return apiRequest<EditorialItemPage>(`/editorial-items?${params.toString()}`, {
        workspaceId: workspaceId!,
      });
    },
    enabled: Boolean(workspaceId),
  });

  async function refreshQueue() {
    await queryClient.invalidateQueries({ queryKey: ["editorial-items"] });
  }

  async function updateItem(item: EditorialItem, changes: Record<string, unknown>) {
    if (!workspaceId) return;
    setBusyId(item.id);
    try {
      await apiRequest(`/editorial-items/${item.id}`, {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify(changes),
      });
      notify("审核队列已更新");
      await refreshQueue();
    } catch (error) {
      notify(error instanceof Error ? error.message : "审核队列更新失败", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function bulkUpdate(changes: Record<string, unknown>) {
    if (!workspaceId || selectedIds.length === 0) return;
    setBulkBusy(true);
    try {
      const result = await apiRequest<{ updated_count: number }>("/editorial-items/bulk", {
        method: "PATCH",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ item_ids: selectedIds, ...changes }),
      });
      notify(`已批量更新 ${result.updated_count} 条审核条目`);
      setSelectedIds([]);
      setBulkStatus("");
      setBulkAssignee("");
      await refreshQueue();
    } catch (error) {
      notify(error instanceof Error ? error.message : "批量更新失败", "error");
    } finally {
      setBulkBusy(false);
    }
  }

  async function saveView() {
    if (!workspaceId || !viewName.trim()) {
      notify("请先填写保存视图名称", "error");
      return;
    }
    try {
      await apiRequest<EditorialSavedView>("/editorial-views", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          name: viewName.trim(),
          status: filter === "all" || filter === "overdue" ? null : filter,
          assignee_id: assigneeFilter && assigneeFilter !== "__none__" ? assigneeFilter : null,
          unassigned: assigneeFilter === "__none__",
          overdue: filter === "overdue",
          priority_min: priorityMin ? Number(priorityMin) : null,
          priority_max: priorityMax ? Number(priorityMax) : null,
        }),
      });
      setViewName("");
      notify("团队视图已保存");
      await queryClient.invalidateQueries({ queryKey: ["editorial-views"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存视图失败", "error");
    }
  }

  async function deleteView() {
    const view = viewsQuery.data?.find((item) => item.id === selectedViewId);
    if (!workspaceId || !view) return;
    if (!canManageViews && view.created_by !== currentUser?.user.id) {
      notify("只有创建者或工作区管理员可以删除该视图", "error");
      return;
    }
    try {
      await apiRequest(`/editorial-views/${view.id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      setSelectedViewId("");
      notify("团队视图已删除");
      await queryClient.invalidateQueries({ queryKey: ["editorial-views"] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除视图失败", "error");
    }
  }

  function applyView(viewId: string) {
    setSelectedViewId(viewId);
    const view = viewsQuery.data?.find((item) => item.id === viewId);
    if (!view) return;
    setFilter(view.overdue ? "overdue" : view.status ?? "all");
    setAssigneeFilter(view.unassigned ? "__none__" : view.assignee_id ?? "");
    setPriorityMin(view.priority_min === null ? "" : String(view.priority_min));
    setPriorityMax(view.priority_max === null ? "" : String(view.priority_max));
    setSelectedIds([]);
  }

  if (query.error) {
    return (
      <StatePanel
        type="error"
        title="审核队列加载失败"
        detail={query.error.message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const items = query.data?.items ?? [];
  const members = membersQuery.data ?? [];
  const allSelected = items.length > 0 && items.every((item) => selectedIds.includes(item.id));

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col gap-4 border-b border-slate-800/80 pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold tracking-[0.24em] text-cyan-300 uppercase">
              Editorial Queue
            </p>
            <h1 className="mt-3 text-3xl font-semibold text-white">编辑审核工作台</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              团队可以分派负责人、批量推进审核状态并保存共享视图。批准只代表编辑通过，不代表已经发布到第三方平台。
            </p>
          </div>
          <Link className={buttonClass} href="/generate">
            创建内容包
          </Link>
        </header>

        <Panel className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="text-slate-500" size={16} />
            {filters.map((value) => (
              <button
                className={filter === value ? buttonClass : secondaryButtonClass}
                key={value}
                onClick={() => {
                  setFilter(value);
                  setSelectedViewId("");
                }}
                type="button"
              >
                {value === "overdue" ? "逾期" : value === "all" ? "全部" : statusLabels[value]}
              </button>
            ))}
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_140px_140px_auto]">
            <select
              className={inputClass}
              onChange={(event) => applyView(event.target.value)}
              value={selectedViewId}
            >
              <option value="">选择团队保存视图</option>
              {(viewsQuery.data ?? []).map((view) => (
                <option key={view.id} value={view.id}>
                  {view.name}
                </option>
              ))}
            </select>
            <select
              className={inputClass}
              onChange={(event) => {
                setAssigneeFilter(event.target.value);
                setSelectedViewId("");
              }}
              value={assigneeFilter}
            >
              <option value="">全部负责人</option>
              <option value="__none__">未分派</option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.display_name}
                </option>
              ))}
            </select>
            <input
              className={inputClass}
              max={100}
              min={0}
              onChange={(event) => {
                setPriorityMin(event.target.value);
                setSelectedViewId("");
              }}
              placeholder="最低优先级"
              type="number"
              value={priorityMin}
            />
            <input
              className={inputClass}
              max={100}
              min={0}
              onChange={(event) => {
                setPriorityMax(event.target.value);
                setSelectedViewId("");
              }}
              placeholder="最高优先级"
              type="number"
              value={priorityMax}
            />
            <button
              className={secondaryButtonClass}
              onClick={() => {
                setFilter("all");
                setAssigneeFilter("");
                setPriorityMin("");
                setPriorityMax("");
                setSelectedViewId("");
              }}
              type="button"
            >
              清除筛选
            </button>
          </div>
          {canEdit && (
            <div className="flex flex-wrap gap-2">
              <input
                className={`${inputClass} min-w-60 flex-1`}
                maxLength={100}
                onChange={(event) => setViewName(event.target.value)}
                placeholder="例如：本周待审核 · 高优先级"
                value={viewName}
              />
              <button className={secondaryButtonClass} onClick={() => void saveView()} type="button">
                <Save size={14} /> 保存当前视图
              </button>
              {selectedViewId && (
                <button className={secondaryButtonClass} onClick={() => void deleteView()} type="button">
                  <Trash2 size={14} /> 删除视图
                </button>
              )}
            </div>
          )}
        </Panel>

        {selectedIds.length > 0 && canEdit && (
          <Panel className="flex flex-wrap items-center gap-3 border-cyan-900/70 p-4">
            <span className="inline-flex items-center gap-2 text-sm text-cyan-200">
              <CheckSquare size={16} /> 已选 {selectedIds.length} 条
            </span>
            <select
              className={inputClass}
              onChange={(event) => setBulkStatus(event.target.value as EditorialStatus | "")}
              value={bulkStatus}
            >
              <option value="">批量变更状态…</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button
              className={secondaryButtonClass}
              disabled={!bulkStatus || bulkBusy}
              onClick={() => void bulkUpdate({ status: bulkStatus })}
              type="button"
            >
              应用状态
            </button>
            <select
              className={inputClass}
              onChange={(event) => setBulkAssignee(event.target.value)}
              value={bulkAssignee}
            >
              <option value="">批量分派负责人…</option>
              <option value="__none__">清除负责人</option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.display_name}
                </option>
              ))}
            </select>
            <button
              className={secondaryButtonClass}
              disabled={!bulkAssignee || bulkBusy}
              onClick={() =>
                void bulkUpdate({ assignee_id: bulkAssignee === "__none__" ? null : bulkAssignee })
              }
              type="button"
            >
              应用分派
            </button>
            <button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setSelectedIds([])} type="button">
              取消选择
            </button>
          </Panel>
        )}

        <Panel>
          {query.isLoading ? (
            <div className="p-10 text-center text-sm text-slate-500">加载审核队列…</div>
          ) : items.length === 0 ? (
            <div className="p-12 text-center">
              <ClipboardCheck className="mx-auto text-slate-600" size={30} />
              <p className="mt-4 text-sm text-slate-400">暂无符合条件的审核条目</p>
              <p className="mt-1 text-xs text-slate-600">
                在生成详情页点击“提交审核”即可把完成的内容包加入队列。
              </p>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 border-b border-slate-800 px-5 py-3 text-xs text-slate-500">
                <input
                  aria-label="选择当前页全部条目"
                  checked={allSelected}
                  onChange={() => setSelectedIds(allSelected ? [] : items.map((item) => item.id))}
                  type="checkbox"
                />
                <span>当前页 {query.data?.total ?? items.length} 条</span>
                {membersQuery.isLoading && <span>成员目录加载中…</span>}
              </div>
              <div className="divide-y divide-slate-800">
                {items.map((item) => (
                  <EditorialRow
                    canEdit={canEdit}
                    canReview={canReview}
                    item={item}
                    members={members}
                    busy={busyId === item.id}
                    key={item.id}
                    onSelect={(checked) =>
                      setSelectedIds((current) =>
                        checked
                          ? [...new Set([...current, item.id])]
                          : current.filter((id) => id !== item.id),
                      )
                    }
                    onUpdate={updateItem}
                    selected={selectedIds.includes(item.id)}
                  />
                ))}
              </div>
            </>
          )}
        </Panel>
      </div>
    </main>
  );
}

function EditorialRow({
  item,
  members,
  canEdit,
  canReview,
  busy,
  selected,
  onSelect,
  onUpdate,
}: {
  item: EditorialItem;
  members: EditorialMember[];
  canEdit: boolean;
  canReview: boolean;
  busy: boolean;
  selected: boolean;
  onSelect: (checked: boolean) => void;
  onUpdate: (item: EditorialItem, changes: Record<string, unknown>) => Promise<void>;
}) {
  const [note, setNote] = useState(item.review_note ?? "");
  const source = item.source_snapshot;
  const assignee = members.find((member) => member.id === item.assignee_id);
  return (
    <article className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <input aria-label={`选择 ${item.title}`} checked={selected} onChange={(event) => onSelect(event.target.checked)} type="checkbox" />
          <Badge tone={statusTones[item.status]}>{statusLabels[item.status]}</Badge>
          <span className="text-xs text-slate-500">优先级 {item.priority}</span>
          {Boolean(source.provider_is_mock) && <Badge tone="warning">Mock Provider</Badge>}
        </div>
        <Link
          className="mt-3 block truncate text-lg font-medium text-cyan-200 hover:text-cyan-100"
          href={`/generations/${item.generation_run_id}`}
        >
          {item.title}
        </Link>
        <p className="mt-2 text-xs text-slate-500">
          来源：{String(source.input_type ?? "未知")} · {String(source.source_kind ?? "unknown")}
          {source.source_url ? ` · ${String(source.source_url)}` : ""}
        </p>
        <textarea
          className={`${inputClass} mt-4 min-h-20 w-full resize-y`}
          disabled={!canEdit || busy}
          onChange={(event) => setNote(event.target.value)}
          placeholder="审核备注（可选）"
          value={note}
        />
      </div>
      <div className="flex flex-col justify-between gap-3 lg:items-end">
        <div className="w-full space-y-2 text-right text-xs text-slate-500">
          <p className="inline-flex items-center gap-1">
            <Clock3 size={13} /> {item.due_at ? new Date(item.due_at).toLocaleString("zh-CN") : "未设置截止时间"}
          </p>
          <p className="mt-1">更新于 {new Date(item.updated_at).toLocaleString("zh-CN")}</p>
          <label className="flex items-center justify-end gap-2 text-left text-xs text-slate-400">
            <UserRound size={14} />
            <select
              aria-label={`分派 ${item.title}`}
              className={`${inputClass} min-w-40`}
              disabled={!canEdit || busy}
              onChange={(event) => void onUpdate(item, { assignee_id: event.target.value || null })}
              value={item.assignee_id ?? ""}
            >
              <option value="">未分派</option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </label>
          {assignee && <p className="text-[11px] text-slate-600">负责人：{assignee.display_name}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          {canEdit && note !== (item.review_note ?? "") && (
            <button className={secondaryButtonClass} disabled={busy} onClick={() => void onUpdate(item, { review_note: note })} type="button">
              保存备注
            </button>
          )}
          {canEdit && item.status === "draft" && (
            <button className={buttonClass} disabled={busy} onClick={() => void onUpdate(item, { status: "in_review", review_note: note || null })} type="button">
              <ClipboardCheck size={14} /> 提交审核
            </button>
          )}
          {canReview && item.status === "in_review" && (
            <>
              <button className={buttonClass} disabled={busy} onClick={() => void onUpdate(item, { status: "approved", review_note: note || null })} type="button">
                <Check size={14} /> 批准
              </button>
              <button className={secondaryButtonClass} disabled={busy} onClick={() => void onUpdate(item, { status: "rejected", review_note: note || null })} type="button">
                <X size={14} /> 退回
              </button>
            </>
          )}
          {canEdit && item.status === "rejected" && (
            <button className={secondaryButtonClass} disabled={busy} onClick={() => void onUpdate(item, { status: "draft" })} type="button">
              <RotateCcw size={14} /> 重新编辑
            </button>
          )}
          {canEdit && item.status === "approved" && (
            <button className={secondaryButtonClass} disabled={busy} onClick={() => void onUpdate(item, { status: "archived" })} type="button">
              归档
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
