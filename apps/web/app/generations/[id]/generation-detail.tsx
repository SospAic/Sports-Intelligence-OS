"use client";

import type { GenerationRun, ProblemDetails } from "@sio/shared-types";
import {
  Clipboard,
  Download,
  FileCheck2,
  RefreshCw,
  Save,
  Search,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Badge, buttonClass, secondaryButtonClass } from "@/components/ui";
import {
  generationInputTypeLabel,
  generationProgress,
  generationSourceTitle,
  generationStatusLabel,
  generationVerificationLabel,
  outputList,
  outputText,
} from "@/lib/generation-presentation";

async function csrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "include" });
  if (!response.ok) throw new Error("无法获取 CSRF Token");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function fail(response: Response): Promise<never> {
  const problem = (await response
    .json()
    .catch(() => null)) as ProblemDetails | null;
  throw new Error(problem?.detail ?? `请求失败（${response.status}）`);
}

export function GenerationDetail({
  workspaceId,
  run,
}: {
  workspaceId: string;
  run: GenerationRun;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const output = useMemo(() => run.final_output ?? {}, [run.final_output]);
  const progress = generationProgress(run);
  const isActive = run.status === "queued" || run.status === "running";
  const tts = outputText(output, "tts_en");
  const translation = outputText(output, "translation_zh");
  const factSummary = outputText(output, "event_fact_summary");
  const storyValue = outputText(output, "story_value");
  const titleEn = outputText(output, "video_title_en");
  const titleZh = outputText(output, "video_title_zh");
  const projectFilename = outputText(output, "project_filename");

  useEffect(() => {
    if (!isActive) return;
    const timer = window.setInterval(() => router.refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [isActive, router]);

  async function action(kind: "retry" | "rewrite" | "save") {
    setBusy(true);
    try {
      const endpoint =
        kind === "save"
          ? `/api/v1/generations/${run.id}/decision`
          : `/api/v1/generations/${run.id}/${kind}`;
      const response = await fetch(endpoint, {
        method: kind === "save" ? "PATCH" : "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": await csrf(),
          "X-Workspace-Id": workspaceId,
        },
        body: JSON.stringify(
          kind === "rewrite"
            ? { instruction }
            : kind === "save"
              ? { is_saved: !run.is_saved }
              : {},
        ),
      });
      if (!response.ok) await fail(response);
      const result = (await response.json()) as GenerationRun;
      if (kind === "rewrite") router.push(`/generations/${result.id}`);
      else {
        setStatus(kind === "save" ? "采用状态已保存" : "已重新加入生成队列");
        router.refresh();
      }
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function copy(label: string, value: string) {
    if (!value) return;
    await navigator.clipboard.writeText(value);
    setStatus(`${label}已复制`);
  }

  async function download(format: "json" | "txt") {
    const response = await fetch(
      `/api/v1/generations/${run.id}/export?format=${format}`,
      { headers: { "X-Workspace-Id": workspaceId }, credentials: "include" },
    );
    if (!response.ok) return setStatus("导出失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `generation-${run.id}.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-col gap-4 border-b border-slate-800/80 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold tracking-[.22em] text-cyan-400 uppercase">
            Content Package
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-white lg:text-3xl">
            {generationSourceTitle(run)}
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            {generationStatusLabel(run.status)} ·{" "}
            {generationVerificationLabel(run.verification_status)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className={secondaryButtonClass} href="/generate">
            <Sparkles size={15} /> 创建新内容
          </Link>
          <button
            className={secondaryButtonClass}
            onClick={() => download("txt")}
            type="button"
          >
            <Download size={15} /> 导出 TXT
          </button>
        </div>
      </header>

      {run.metadata.provider_is_mock ? (
        <div className="rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-200">
          这是明确标记的 Mock 测试输出，不代表真实 LLM 生成或事实已经联网核实。
        </div>
      ) : null}

      <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-100">
              {progress.current}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              系统会在后台完成事实整理、规则应用、文案生成和质量检查。
            </p>
          </div>
          <span className="text-sm font-semibold text-cyan-300">
            {progress.percent}%
          </span>
        </div>
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-cyan-400 transition-[width]"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
      </section>

      {run.error ? (
        <div className="rounded-xl border border-rose-900/60 bg-rose-950/20 p-4 text-sm text-rose-200">
          <p>{run.error.message ?? "内容生成失败"}</p>
          <button
            className="mt-3 inline-flex items-center gap-2 rounded border border-rose-800 px-3 py-1.5 text-xs"
            disabled={busy}
            onClick={() => action("retry")}
            type="button"
          >
            <RefreshCw size={13} /> 重新生成
          </button>
        </div>
      ) : null}

      {run.status === "completed" && run.final_output ? (
        <>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
            <OutputCard
              action={() => copy("英文 TTS", tts)}
              actionLabel="复制文案"
              className="xl:row-span-2"
              eyebrow="PRIMARY SCRIPT"
              title="英文 TTS 文案"
              value={tts}
            />
            <OutputCard
              action={() => copy("中文翻译", translation)}
              actionLabel="复制翻译"
              eyebrow="TRANSLATION"
              title="中文翻译"
              value={translation}
            />
            <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
              <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
                TITLES
              </p>
              <h2 className="mt-2 text-lg font-semibold text-white">
                视频标题
              </h2>
              <div className="mt-4 space-y-3">
                <CopyLine
                  label="英文"
                  onCopy={() => copy("英文标题", titleEn)}
                  value={titleEn}
                />
                <CopyLine
                  label="中文"
                  onCopy={() => copy("中文标题", titleZh)}
                  value={titleZh}
                />
              </div>
            </section>
          </div>

          <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
            <ListCard
              icon={<Search size={17} />}
              items={outputList(output, "search_keywords")}
              title="视频搜索关键词"
            />
            <ListCard
              icon={<FileCheck2 size={17} />}
              items={outputList(output, "material_keywords")}
              title="素材搜索关键词"
            />
            <ListCard
              icon={<Sparkles size={17} />}
              items={outputList(output, "tags")}
              title="发布标签"
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
            <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
              <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
                FACTS & STORY
              </p>
              <h2 className="mt-2 text-lg font-semibold text-white">
                事实与故事判断
              </h2>
              <div className="mt-5 grid gap-5 md:grid-cols-2">
                <TextBlock label="事件事实摘要" value={factSummary} />
                <TextBlock label="故事价值" value={storyValue} />
              </div>
              <div className="mt-5 border-t border-slate-800 pt-5">
                <TextBlock
                  label="事实来源"
                  value={outputText(output, "fact_sources")}
                />
              </div>
            </section>
            <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
              <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
                DELIVERY
              </p>
              <h2 className="mt-2 text-lg font-semibold text-white">
                成片交付
              </h2>
              <dl className="mt-5 space-y-4 text-sm">
                <div>
                  <dt className="text-xs text-slate-500">工程文件名</dt>
                  <dd className="mt-1 font-medium text-slate-100">
                    {projectFilename || "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">质量检查</dt>
                  <dd className="mt-1">
                    <Badge
                      tone={
                        run.validation_result.valid === false
                          ? "warning"
                          : "success"
                      }
                    >
                      {run.validation_result.valid === false
                        ? "存在待处理项"
                        : "检查通过"}
                    </Badge>
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">自动重写</dt>
                  <dd className="mt-1 text-slate-300">
                    {run.rewrite_count} 次
                  </dd>
                </div>
              </dl>
              <button
                className={`${buttonClass} mt-5 w-full`}
                disabled={busy}
                onClick={() => action("save")}
                type="button"
              >
                <Save size={15} /> {run.is_saved ? "取消采用" : "保存并采用"}
              </button>
            </section>
          </div>

          <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
            <h2 className="text-lg font-semibold text-white">
              不满意？重新生成
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              写下需要调整的地方，系统会保留当前成品并创建一份新版本。
            </p>
            <div className="mt-4 flex flex-col gap-3 lg:flex-row">
              <textarea
                className="min-h-24 flex-1 rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-slate-100 outline-none focus:border-cyan-500"
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="例如：Hook 更快进入比赛动作，保留所有已核实事实。"
                value={instruction}
              />
              <button
                className={`${secondaryButtonClass} self-end`}
                disabled={busy || !instruction.trim()}
                onClick={() => action("rewrite")}
                type="button"
              >
                <RefreshCw size={15} /> 按要求重做
              </button>
            </div>
          </section>
        </>
      ) : !run.error ? (
        <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-10 text-center">
          <Sparkles className="mx-auto animate-pulse text-cyan-300" size={28} />
          <h2 className="mt-4 font-medium text-slate-100">正在制作内容包</h2>
          <p className="mt-2 text-sm text-slate-500">
            页面会自动更新，无需查看或配置内部 Prompt 步骤。
          </p>
        </div>
      ) : null}

      <details className="rounded-2xl border border-slate-800 bg-slate-950/50 p-5 text-sm">
        <summary className="cursor-pointer text-slate-400">
          审计与技术信息
        </summary>
        <div className="mt-5 grid gap-4 text-xs text-slate-400 md:grid-cols-2 xl:grid-cols-4">
          <AuditValue label="运行 ID" value={run.id} />
          <AuditValue label="规则版本" value={run.rule_set_version_id} />
          <AuditValue label="内容模板版本" value={run.prompt_version_id} />
          <AuditValue
            label="内容引擎"
            value={`${run.provider} · ${run.model}`}
          />
          <AuditValue
            label="Token"
            value={String(run.token_usage.total_tokens ?? "—")}
          />
          <AuditValue
            label="估算成本"
            value={String(run.estimated_cost ?? "不可用")}
          />
          <AuditValue
            label="核实状态"
            value={generationVerificationLabel(run.verification_status)}
          />
          <AuditValue
            label="输入类型"
            value={generationInputTypeLabel(run.input_type)}
          />
        </div>
        <ol className="mt-5 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
          {run.steps.map((step) => (
            <li
              className="rounded-lg border border-slate-800 p-3"
              key={step.id}
            >
              <span className="text-[10px] text-slate-600">
                {step.sort_order}/{progress.total}
              </span>
              <p className="mt-1 text-xs text-slate-300">{step.name}</p>
              <p className="mt-1 text-[10px] text-cyan-400">{step.status}</p>
            </li>
          ))}
        </ol>
        <div className="mt-5 grid gap-4 border-t border-slate-800 pt-5 lg:grid-cols-3">
          <TextBlock
            label="完整 QA 报告"
            value={
              outputText(output, "qa_report") ||
              JSON.stringify(run.validation_result, null, 2)
            }
          />
          <TextBlock
            label="实际使用规则"
            value={outputText(output, "used_rules")}
          />
          <TextBlock
            label="触发的重写原因"
            value={outputText(output, "rewrite_reasons")}
          />
        </div>
        <button
          className="mt-4 text-xs text-slate-500 hover:text-slate-300"
          onClick={() => download("json")}
          type="button"
        >
          导出完整审计 JSON
        </button>
      </details>

      {status ? (
        <p
          className="rounded-lg border border-slate-800 bg-slate-950 p-3 text-sm text-slate-300"
          role="status"
        >
          {status}
        </p>
      ) : null}
    </div>
  );
}

function OutputCard({
  title,
  eyebrow,
  value,
  actionLabel,
  action,
  className = "",
}: {
  title: string;
  eyebrow: string;
  value: string;
  actionLabel: string;
  action: () => void;
  className?: string;
}) {
  return (
    <section
      className={`rounded-2xl border border-slate-800 bg-slate-950/70 p-5 ${className}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            {eyebrow}
          </p>
          <h2 className="mt-2 text-lg font-semibold text-white">{title}</h2>
        </div>
        <button
          className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-900 disabled:opacity-50"
          disabled={!value}
          onClick={action}
          type="button"
        >
          <Clipboard size={13} /> {actionLabel}
        </button>
      </div>
      <p className="mt-5 whitespace-pre-wrap text-sm leading-7 text-slate-200">
        {value || "暂无内容"}
      </p>
    </section>
  );
}

function CopyLine({
  label,
  value,
  onCopy,
}: {
  label: string;
  value: string;
  onCopy: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-slate-800 p-3">
      <div>
        <p className="text-[10px] text-slate-500">{label}</p>
        <p className="mt-1 text-sm leading-6 text-slate-200">{value || "—"}</p>
      </div>
      <button
        aria-label={`复制${label}标题`}
        className="shrink-0 text-slate-500 hover:text-cyan-300 disabled:opacity-40"
        disabled={!value}
        onClick={onCopy}
        type="button"
      >
        <Clipboard size={14} />
      </button>
    </div>
  );
}

function ListCard({
  title,
  items,
  icon,
}: {
  title: string;
  items: string[];
  icon: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
      <div className="flex items-center gap-2 text-cyan-300">
        {icon}
        <h2 className="text-sm font-medium text-slate-100">{title}</h2>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {items.length ? (
          items.map((item) => (
            <span
              className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300"
              key={item}
            >
              {item}
            </span>
          ))
        ) : (
          <span className="text-xs text-slate-500">暂无内容</span>
        )}
      </div>
    </section>
  );
}

function TextBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">
        {value || "—"}
      </p>
    </div>
  );
}

function AuditValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-slate-600">{label}</p>
      <p className="mt-1 break-all text-slate-300">{value}</p>
    </div>
  );
}
