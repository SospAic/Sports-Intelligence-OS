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
          {/* ── 主视图：英文 TTS + 翻译 + 标题 ─────────────────────────────── */}
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

          {/* ── 关键词与标签 ────────────────────────────────────────────────── */}
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

          {/* ── 事实与故事判断 + 成片交付 ───────────────────────────────────── */}
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
                  <dt className="text-xs text-slate-500">精确字符数</dt>
                  <dd className="mt-1 font-mono text-slate-300">
                    {output["spoken_char_count"] != null
                      ? String(output["spoken_char_count"])
                      : "—"}
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

          {/* ── B 组：7.9 完整叙事包 ────────────────────────────────────────── */}
          <FullNarrativePackage
            onCopy={copy}
            output={output}
          />

          {/* ── 重新生成 ─────────────────────────────────────────────────────── */}
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

      {/* ── 审计与技术信息 ─────────────────────────────────────────────────── */}
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

// ── B/C 组：7.9 完整叙事包展开区 ─────────────────────────────────────────────
function FullNarrativePackage({
  output,
  onCopy,
}: {
  output: Record<string, unknown>;
  onCopy: (label: string, value: string) => void;
}) {
  const storyFormat = output["story_format"];
  const storyFormatReason = output["story_format_reason"];
  const centralQuestion = output["central_question"];
  const selectedHook = output["selected_hook"];
  const hookCandidates = output["hook_candidates"];
  const storyArch = output["story_architecture"];
  const lcrEnabled = output["lcr_enabled"];
  const lcrReason = output["lcr_reason"];
  const cmssml = typeof output["cmssml"] === "string" ? output["cmssml"] : null;
  const ev3 = typeof output["ev3"] === "string" ? output["ev3"] : null;
  const eventIdentity = output["event_identity"];
  const answerWordMap = output["answer_word_map"];
  const reactionRelay = output["reaction_relay"];
  const evidenceRewards = output["evidence_rewards"];
  const exclusionLadder = output["exclusion_ladder"];
  const dialogueNotes = output["dialogue_notes"];

  // C 组 ambiguous 字段
  const audioMap = output["audio_performance_map"];
  const ttsSettings = output["tts_settings"];
  const materialPlan = output["video_material_plan"];
  const editMap = output["edit_map"];

  const hasAnyBField =
    storyFormat != null ||
    centralQuestion != null ||
    selectedHook != null ||
    cmssml != null ||
    ev3 != null ||
    storyArch != null;

  if (!hasAnyBField) return null;

  return (
    <details className="rounded-2xl border border-slate-700 bg-slate-950/60 p-5">
      <summary className="cursor-pointer text-sm font-semibold text-slate-200">
        完整叙事包（7.9 Full Package）
      </summary>
      <p className="mt-2 text-xs text-slate-500">
        包含故事架构、Hook 分析、CMSSML、EV3 和叙事决策说明。带 ⚠ 标注的字段来自原文不完整条目（ambiguous），为系统辅助生成。
      </p>

      {/* 事件识别 */}
      {eventIdentity != null && (
        <div className="mt-5 rounded-xl border border-slate-800 p-4">
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            EVENT IDENTITY
          </p>
          <h3 className="mt-2 text-sm font-medium text-slate-100">事件精确识别</h3>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
            {JSON.stringify(eventIdentity, null, 2)}
          </pre>
        </div>
      )}

      {/* 故事格式与中心悬念 */}
      {(storyFormat != null || centralQuestion != null) && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {storyFormat != null && (
            <div className="rounded-xl border border-slate-800 p-4">
              <p className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                STORY FORMAT
              </p>
              <p className="mt-2 text-sm font-medium text-slate-100">
                {typeof storyFormat === "string" ? storyFormat : JSON.stringify(storyFormat)}
              </p>
              {storyFormatReason != null && (
                <p className="mt-2 text-xs text-slate-400">
                  {typeof storyFormatReason === "string"
                    ? storyFormatReason
                    : JSON.stringify(storyFormatReason)}
                </p>
              )}
            </div>
          )}
          {centralQuestion != null && (
            <div className="rounded-xl border border-slate-800 p-4">
              <p className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                CENTRAL QUESTION
              </p>
              <p className="mt-2 text-sm text-slate-200">
                {typeof centralQuestion === "string"
                  ? centralQuestion
                  : JSON.stringify(centralQuestion)}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Hook 分析 */}
      {(selectedHook != null || hookCandidates != null) && (
        <div className="mt-4 rounded-xl border border-slate-800 p-4">
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            HOOK ANALYSIS
          </p>
          <h3 className="mt-2 text-sm font-medium text-slate-100">Hook 分析</h3>
          {selectedHook != null && (
            <div className="mt-3">
              <p className="text-[10px] text-slate-500">选定 Hook</p>
              <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
                {JSON.stringify(selectedHook, null, 2)}
              </pre>
            </div>
          )}
          {Array.isArray(hookCandidates) && hookCandidates.length > 0 && (
            <div className="mt-3">
              <p className="text-[10px] text-slate-500">全部候选（{hookCandidates.length} 个）</p>
              <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
                {JSON.stringify(hookCandidates, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* CMSSML / EV3 */}
      {(cmssml != null || ev3 != null) && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {cmssml != null && (
            <div className="rounded-xl border border-slate-800 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                  CMSSML
                </p>
                <button
                  aria-label="复制 CMSSML"
                  className="text-slate-500 hover:text-cyan-300"
                  onClick={() => onCopy("CMSSML", cmssml)}
                  type="button"
                >
                  <Clipboard size={13} />
                </button>
              </div>
              <p className="mt-2 break-all text-xs leading-6 text-slate-300 font-mono">
                {cmssml}
              </p>
            </div>
          )}
          {ev3 != null && (
            <div className="rounded-xl border border-slate-800 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">
                  EV3
                </p>
                <button
                  aria-label="复制 EV3"
                  className="text-slate-500 hover:text-cyan-300"
                  onClick={() => onCopy("EV3", ev3)}
                  type="button"
                >
                  <Clipboard size={13} />
                </button>
              </div>
              <p className="mt-2 break-all text-xs leading-6 text-slate-300 font-mono">
                {ev3}
              </p>
            </div>
          )}
        </div>
      )}

      {/* 故事架构 */}
      {storyArch != null && (
        <div className="mt-4 rounded-xl border border-slate-800 p-4">
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            STORY ARCHITECTURE
          </p>
          <h3 className="mt-2 text-sm font-medium text-slate-100">故事架构</h3>
          {typeof lcrEnabled === "boolean" && (
            <div className="mt-3 flex items-center gap-2">
              <Badge tone={lcrEnabled ? "success" : "neutral"}>
                LCR {lcrEnabled ? "已启用" : "未启用"}
              </Badge>
              {lcrReason != null && (
                <span className="text-xs text-slate-400">
                  {typeof lcrReason === "string" ? lcrReason : JSON.stringify(lcrReason)}
                </span>
              )}
            </div>
          )}
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
            {JSON.stringify(storyArch, null, 2)}
          </pre>
        </div>
      )}

      {/* 答案词映射 */}
      {answerWordMap != null && (
        <div className="mt-4 rounded-xl border border-slate-800 p-4">
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            ANSWER WORD MAP
          </p>
          <h3 className="mt-2 text-sm font-medium text-slate-100">答案词与泄露映射</h3>
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-300">
            {JSON.stringify(answerWordMap, null, 2)}
          </pre>
        </div>
      )}

      {/* RR / EER / EL / 对话说明 */}
      {(reactionRelay != null || evidenceRewards != null || exclusionLadder != null || dialogueNotes != null) && (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {reactionRelay != null && (
            <NarrativeDetail label="Reaction Relay 结构" value={reactionRelay} />
          )}
          {evidenceRewards != null && (
            <NarrativeDetail label="证据奖励结构（EER）" value={evidenceRewards} />
          )}
          {exclusionLadder != null && (
            <NarrativeDetail label="合理解释排除列表（EL）" value={exclusionLadder} />
          )}
          {dialogueNotes != null && (
            <NarrativeDetail label="对话与心理说明" value={dialogueNotes} />
          )}
        </div>
      )}

      {/* C 组：ambiguous 字段 */}
      {(audioMap != null || ttsSettings != null || materialPlan != null || editMap != null) && (
        <div className="mt-5 rounded-xl border border-slate-700/50 bg-slate-900/30 p-4">
          <p className="text-xs text-slate-500">
            ⚠ 以下字段来自 7.9 原文不完整条目（ambiguous），为系统辅助生成，不能作为完整规则依据。
          </p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {audioMap != null && (
              <NarrativeDetail label="Audio Performance Map" value={audioMap} />
            )}
            {ttsSettings != null && (
              <NarrativeDetail label="TTS 设置建议" value={ttsSettings} />
            )}
            {materialPlan != null && (
              <NarrativeDetail label="视频素材逐 Beat 计划" value={materialPlan} />
            )}
            {editMap != null && (
              <NarrativeDetail label="剪辑 Map" value={editMap} />
            )}
          </div>
        </div>
      )}
    </details>
  );
}

// ── 共用子组件 ────────────────────────────────────────────────────────────────

function NarrativeDetail({ label, value }: { label: string; value: unknown }) {
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="rounded-xl border border-slate-800 p-4">
      <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
        {label}
      </p>
      <pre className="mt-2 overflow-x-auto text-xs leading-5 text-slate-300 whitespace-pre-wrap">
        {text}
      </pre>
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
