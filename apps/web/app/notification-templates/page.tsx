"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  History,
  Pencil,
  Plus,
  RotateCcw,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";
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

// ---------------------------------------------------------------------------
// Types matching the backend schemas
// ---------------------------------------------------------------------------

interface TemplateSummary {
  id: string;
  name: string;
  description: string | null;
  category: string;
  created_at: string;
  updated_at: string;
  current_version: number | null;
}

interface TemplateVersion {
  id: string;
  version: number;
  status: "draft" | "published" | "archived";
  subject_template: string;
  body_template: string;
  variables_schema: Record<string, unknown>;
  created_at: string;
  published_at: string | null;
}

interface TemplateDetail extends TemplateSummary {
  versions: TemplateVersion[];
}

interface TemplatePage {
  items: TemplateSummary[];
  page: number;
  page_size: number;
  total: number;
}

// ---------------------------------------------------------------------------
// Create-modal state
// ---------------------------------------------------------------------------

interface CreateForm {
  name: string;
  description: string;
  category: string;
  subject_template: string;
  body_template: string;
}

const emptyCreateForm: CreateForm = {
  name: "",
  description: "",
  category: "general",
  subject_template: "",
  body_template: "",
};

// ---------------------------------------------------------------------------
// Edit-draft state
// ---------------------------------------------------------------------------

interface EditDraftForm {
  subject_template: string;
  body_template: string;
  change_notes: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NotificationTemplatesPage() {
  const { workspaceId, role } = useWorkspace();
  const { notify } = useToast();
  const qc = useQueryClient();

  // -- list state
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // -- create modal state
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateForm>(emptyCreateForm);
  const [saving, setSaving] = useState(false);

  // -- edit draft state (scoped to expanded template)
  const [editingDraft, setEditingDraft] = useState(false);
  const [draftForm, setDraftForm] = useState<EditDraftForm>({
    subject_template: "",
    body_template: "",
    change_notes: "",
  });
  const [draftSaving, setDraftSaving] = useState(false);

  const canEdit = ["owner", "admin", "editor"].includes(role ?? "");
  const canAdmin = ["owner", "admin"].includes(role ?? "");

  // -----------------------------------------------------------------------
  // Queries
  // -----------------------------------------------------------------------

  const templates = useQuery({
    queryKey: ["notification-templates", workspaceId],
    queryFn: () =>
      apiRequest<TemplatePage>(
        "/notification-templates?page=1&page_size=100",
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId),
  });

  const detail = useQuery({
    queryKey: ["notification-template-detail", workspaceId, expandedId],
    queryFn: () =>
      apiRequest<TemplateDetail>(
        `/notification-templates/${expandedId}`,
        { workspaceId: workspaceId! },
      ),
    enabled: Boolean(workspaceId && expandedId),
  });

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  function invalidateList() {
    return qc.invalidateQueries({ queryKey: ["notification-templates"] });
  }

  function invalidateDetail(id: string) {
    return qc.invalidateQueries({
      queryKey: ["notification-template-detail", workspaceId, id],
    });
  }

  function invalidateAll(id?: string) {
    invalidateList();
    if (id) invalidateDetail(id);
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  async function createTemplate() {
    if (!workspaceId || !form.name.trim() || !form.subject_template.trim() || !form.body_template.trim()) return;
    setSaving(true);
    try {
      await apiRequest<TemplateDetail>("/notification-templates", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          name: form.name.trim(),
          description: form.description.trim() || null,
          category: form.category.trim() || "general",
          subject_template: form.subject_template,
          body_template: form.body_template,
          variables_schema: {},
        }),
      });
      notify("模板已创建");
      setShowCreate(false);
      setForm(emptyCreateForm);
      await invalidateList();
    } catch (error) {
      notify(error instanceof Error ? error.message : "创建失败", "error");
    } finally {
      setSaving(false);
    }
  }

  async function deleteTemplate(tpl: TemplateSummary) {
    if (!workspaceId || !window.confirm(`确定删除模板「${tpl.name}」及其所有版本？`)) return;
    try {
      await apiRequest<void>(`/notification-templates/${tpl.id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("模板已删除");
      if (expandedId === tpl.id) setExpandedId(null);
      await invalidateList();
    } catch (error) {
      notify(error instanceof Error ? error.message : "删除失败", "error");
    }
  }

  async function publishTemplate(tpl: TemplateSummary) {
    if (!workspaceId) return;
    try {
      await apiRequest<TemplateVersion>(
        `/notification-templates/${tpl.id}/publish`,
        { method: "POST", workspaceId, csrf: true },
      );
      notify("模板版本已发布");
      await invalidateAll(tpl.id);
    } catch (error) {
      notify(error instanceof Error ? error.message : "发布失败", "error");
    }
  }

  async function rollbackToVersion(tpl: TemplateSummary, version: TemplateVersion) {
    if (
      !workspaceId ||
      !window.confirm(`将基于版本 ${version.version} 创建新草稿，确定继续？`)
    )
      return;
    try {
      await apiRequest<TemplateVersion>(
        `/notification-templates/${tpl.id}/rollback`,
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ version_id: version.id }),
        },
      );
      notify(`已基于版本 ${version.version} 创建新草稿`);
      await invalidateAll(tpl.id);
    } catch (error) {
      notify(error instanceof Error ? error.message : "回滚失败", "error");
    }
  }

  function beginEditDraft(ver: TemplateVersion) {
    setDraftForm({
      subject_template: ver.subject_template,
      body_template: ver.body_template,
      change_notes: "",
    });
    setEditingDraft(true);
  }

  async function saveDraft(tpl: TemplateSummary) {
    if (!workspaceId) return;
    setDraftSaving(true);
    try {
      await apiRequest<TemplateVersion>(
        `/notification-templates/${tpl.id}`,
        {
          method: "PUT",
          workspaceId,
          csrf: true,
          body: JSON.stringify({
            subject_template: draftForm.subject_template || undefined,
            body_template: draftForm.body_template || undefined,
            change_notes: draftForm.change_notes || undefined,
          }),
        },
      );
      notify("草稿已保存");
      setEditingDraft(false);
      await invalidateAll(tpl.id);
    } catch (error) {
      notify(error instanceof Error ? error.message : "保存失败", "error");
    } finally {
      setDraftSaving(false);
    }
  }

  // -----------------------------------------------------------------------
  // Derived
  // -----------------------------------------------------------------------

  const items = templates.data?.items ?? [];

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  return (
    <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-7 lg:px-8">
      <PageHeader
        eyebrow="Notifications"
        title="通知模板"
        description="管理通知消息模板及其版本历史。模板支持草稿、发布和回滚，便于安全迭代通知内容。"
        actions={
          canEdit && (
            <button
              className={buttonClass}
              onClick={() => {
                setForm(emptyCreateForm);
                setShowCreate(true);
              }}
            >
              <Plus size={15} />
              新建模板
            </button>
          )
        }
      />

      {/* ---- Create modal ---- */}
      {showCreate && (
        <Panel className="space-y-4 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-medium text-white">新建通知模板</h2>
              <p className="mt-1 text-xs text-slate-500">
                创建模板后将自动生成初始草稿版本，可在发布前反复编辑。
              </p>
            </div>
            <button
              className="text-slate-400 hover:text-white"
              onClick={() => setShowCreate(false)}
            >
              <X size={18} />
            </button>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-2 text-sm">
              <span>
                模板名称 <span className="text-rose-400">*</span>
              </span>
              <input
                className={inputClass}
                placeholder="如：赛事比分提醒"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </label>
            <label className="grid gap-2 text-sm">
              <span>分类</span>
              <input
                className={inputClass}
                placeholder="general"
                value={form.category}
                onChange={(e) =>
                  setForm((f) => ({ ...f, category: e.target.value }))
                }
              />
            </label>
            <label className="grid gap-2 text-sm md:col-span-2">
              <span>描述</span>
              <input
                className={inputClass}
                placeholder="可选描述"
                value={form.description}
                onChange={(e) =>
                  setForm((f) => ({ ...f, description: e.target.value }))
                }
              />
            </label>
            <label className="grid gap-2 text-sm md:col-span-2">
              <span>
                标题模板 <span className="text-rose-400">*</span>
              </span>
              <input
                className={inputClass}
                placeholder='如：{match_title} — {event_time}'
                value={form.subject_template}
                onChange={(e) =>
                  setForm((f) => ({ ...f, subject_template: e.target.value }))
                }
              />
              <span className="text-xs text-slate-500">
                支持 {"{variable}"} 占位符，运行时替换。
              </span>
            </label>
            <label className="grid gap-2 text-sm md:col-span-2">
              <span>
                正文模板 <span className="text-rose-400">*</span>
              </span>
              <textarea
                className={`${inputClass} h-32 py-2 font-mono`}
                placeholder="输入正文内容，支持 {variable} 占位符…"
                value={form.body_template}
                onChange={(e) =>
                  setForm((f) => ({ ...f, body_template: e.target.value }))
                }
              />
            </label>
          </div>

          <div className="flex gap-2">
            <button
              className={buttonClass}
              disabled={
                saving ||
                !form.name.trim() ||
                !form.subject_template.trim() ||
                !form.body_template.trim()
              }
              onClick={createTemplate}
            >
              {saving ? "保存中…" : "创建模板"}
            </button>
            <button
              className={secondaryButtonClass}
              onClick={() => setShowCreate(false)}
            >
              取消
            </button>
          </div>
        </Panel>
      )}

      {/* ---- Template list ---- */}
      {templates.isLoading ? (
        <Panel>
          <SkeletonRows count={4} />
        </Panel>
      ) : templates.error ? (
        <StatePanel
          type="error"
          title="模板列表加载失败"
          detail={templates.error.message}
          onRetry={() => templates.refetch()}
        />
      ) : items.length === 0 ? (
        <StatePanel type="empty" title="尚未创建通知模板" />
      ) : (
        <div className="space-y-3">
          {items.map((tpl) => {
            const isExpanded = expandedId === tpl.id;
            const detailData = isExpanded ? detail.data : undefined;
            const detailLoading = isExpanded && detail.isLoading;
            const versions = detailData?.versions ?? [];
            const latestDraft = versions.find((v) => v.status === "draft");

            return (
              <Panel className="overflow-hidden" key={tpl.id}>
                {/* -- Row header -- */}
                <button
                  className="flex w-full items-center gap-4 p-5 text-left transition hover:bg-slate-900/50"
                  onClick={() => {
                    if (isExpanded) {
                      setExpandedId(null);
                      setEditingDraft(false);
                    } else {
                      setExpandedId(tpl.id);
                      setEditingDraft(false);
                    }
                  }}
                >
                  <span className="text-slate-400">
                    {isExpanded ? (
                      <ChevronDown size={18} />
                    ) : (
                      <ChevronRight size={18} />
                    )}
                  </span>

                  <FileText className="shrink-0 text-cyan-400" size={18} />

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium text-white">
                        {tpl.name}
                      </span>
                      <Badge tone="info">{tpl.category}</Badge>
                      {tpl.current_version !== null && (
                        <Badge tone="neutral">
                          v{tpl.current_version}
                        </Badge>
                      )}
                    </div>
                    {tpl.description && (
                      <p className="mt-1 truncate text-xs text-slate-500">
                        {tpl.description}
                      </p>
                    )}
                  </div>

                  <div className="hidden shrink-0 text-right text-xs text-slate-500 sm:block">
                    <div>创建于 {formatDate(tpl.created_at)}</div>
                    <div>更新于 {formatDate(tpl.updated_at)}</div>
                  </div>

                  {/* Quick actions on the row */}
                  <div className="flex shrink-0 gap-1" onClick={(e) => e.stopPropagation()}>
                    {canEdit && latestDraft && (
                      <button
                        className={`${secondaryButtonClass} h-8 px-2`}
                        title="发布当前草稿"
                        onClick={() => publishTemplate(tpl)}
                      >
                        <Send size={13} />
                        <span className="hidden sm:inline">发布</span>
                      </button>
                    )}
                    {canAdmin && (
                      <button
                        className="ml-1 text-rose-300 hover:text-rose-200"
                        title="删除模板"
                        onClick={() => deleteTemplate(tpl)}
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                </button>

                {/* -- Expanded detail -- */}
                {isExpanded && (
                  <div className="border-t border-slate-800 bg-slate-950/50 p-5">
                    {detailLoading ? (
                      <SkeletonRows count={3} />
                    ) : detail.error ? (
                      <StatePanel
                        type="error"
                        title="模板详情加载失败"
                        detail={detail.error.message}
                        onRetry={() => detail.refetch()}
                      />
                    ) : detailData ? (
                      <div className="space-y-5">
                        {/* Draft editor or current version preview */}
                        {editingDraft && latestDraft && canEdit ? (
                          <div className="space-y-3 rounded-xl border border-slate-700 bg-slate-900 p-4">
                            <div className="flex items-center justify-between">
                              <h3 className="flex items-center gap-2 text-sm font-medium text-white">
                                <Pencil size={14} />
                                编辑草稿（v{latestDraft.version}）
                              </h3>
                              <button
                                className="text-slate-400 hover:text-white"
                                onClick={() => setEditingDraft(false)}
                              >
                                <X size={16} />
                              </button>
                            </div>
                            <label className="grid gap-1 text-sm">
                              <span className="text-slate-400">标题模板</span>
                              <input
                                className={inputClass}
                                value={draftForm.subject_template}
                                onChange={(e) =>
                                  setDraftForm((f) => ({
                                    ...f,
                                    subject_template: e.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label className="grid gap-1 text-sm">
                              <span className="text-slate-400">正文模板</span>
                              <textarea
                                className={`${inputClass} h-28 py-2 font-mono`}
                                value={draftForm.body_template}
                                onChange={(e) =>
                                  setDraftForm((f) => ({
                                    ...f,
                                    body_template: e.target.value,
                                  }))
                                }
                              />
                            </label>
                            <label className="grid gap-1 text-sm">
                              <span className="text-slate-400">变更说明</span>
                              <input
                                className={inputClass}
                                placeholder="可选：本次修改的说明"
                                value={draftForm.change_notes}
                                onChange={(e) =>
                                  setDraftForm((f) => ({
                                    ...f,
                                    change_notes: e.target.value,
                                  }))
                                }
                              />
                            </label>
                            <div className="flex gap-2">
                              <button
                                className={buttonClass}
                                disabled={draftSaving}
                                onClick={() => saveDraft(tpl)}
                              >
                                {draftSaving ? "保存中…" : "保存草稿"}
                              </button>
                              <button
                                className={secondaryButtonClass}
                                onClick={() => setEditingDraft(false)}
                              >
                                取消
                              </button>
                            </div>
                          </div>
                        ) : latestDraft ? (
                          <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                            <div className="flex items-center justify-between">
                              <h3 className="flex items-center gap-2 text-sm font-medium text-amber-300">
                                <Clock size={14} />
                                当前草稿（v{latestDraft.version}）
                              </h3>
                              {canEdit && (
                                <button
                                  className={`${secondaryButtonClass} h-8 px-2`}
                                  onClick={() => beginEditDraft(latestDraft)}
                                >
                                  <Pencil size={13} />
                                  编辑
                                </button>
                              )}
                            </div>
                            <div className="space-y-1 text-sm">
                              <p className="text-slate-400">
                                标题：
                                <span className="font-mono text-slate-200">
                                  {latestDraft.subject_template}
                                </span>
                              </p>
                              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono text-xs text-slate-300">
                                {latestDraft.body_template}
                              </pre>
                            </div>
                          </div>
                        ) : (
                          <p className="text-sm text-slate-500">
                            当前没有草稿版本。
                          </p>
                        )}

                        {/* Version history */}
                        <div>
                          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
                            <History size={14} />
                            版本历史
                            <span className="text-xs font-normal text-slate-500">
                              （共 {versions.length} 个版本）
                            </span>
                          </h3>
                          {versions.length === 0 ? (
                            <p className="text-sm text-slate-500">暂无版本记录。</p>
                          ) : (
                            <div className="overflow-x-auto">
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="border-b border-slate-800 text-xs text-slate-500">
                                    <th className="px-3 py-2 text-left font-medium">版本</th>
                                    <th className="px-3 py-2 text-left font-medium">状态</th>
                                    <th className="px-3 py-2 text-left font-medium">标题模板</th>
                                    <th className="px-3 py-2 text-left font-medium">创建时间</th>
                                    <th className="px-3 py-2 text-left font-medium">发布时间</th>
                                    {canEdit && (
                                      <th className="px-3 py-2 text-right font-medium">操作</th>
                                    )}
                                  </tr>
                                </thead>
                                <tbody>
                                  {versions.map((ver) => (
                                    <tr
                                      className="border-b border-slate-800/60 hover:bg-slate-900/40"
                                      key={ver.id}
                                    >
                                      <td className="px-3 py-2 font-mono text-slate-300">
                                        v{ver.version}
                                      </td>
                                      <td className="px-3 py-2">
                                        <Badge
                                          tone={
                                            ver.status === "published"
                                              ? "success"
                                              : ver.status === "draft"
                                                ? "warning"
                                                : "neutral"
                                          }
                                        >
                                          {ver.status === "published"
                                            ? "已发布"
                                            : ver.status === "draft"
                                              ? "草稿"
                                              : "已归档"}
                                        </Badge>
                                      </td>
                                      <td className="max-w-xs truncate px-3 py-2 font-mono text-xs text-slate-400">
                                        {ver.subject_template}
                                      </td>
                                      <td className="whitespace-nowrap px-3 py-2 text-slate-400">
                                        {formatDate(ver.created_at)}
                                      </td>
                                      <td className="whitespace-nowrap px-3 py-2 text-slate-400">
                                        {ver.published_at
                                          ? formatDate(ver.published_at)
                                          : "—"}
                                      </td>
                                      {canEdit && (
                                        <td className="px-3 py-2 text-right">
                                          {ver.status !== "draft" && (
                                            <button
                                              className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300"
                                              title={`基于 v${ver.version} 创建新草稿`}
                                              onClick={() =>
                                                rollbackToVersion(tpl, ver)
                                              }
                                            >
                                              <RotateCcw size={12} />
                                              回滚
                                            </button>
                                          )}
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      </div>
                    ) : null}
                  </div>
                )}
              </Panel>
            );
          })}
        </div>
      )}
    </main>
  );
}
