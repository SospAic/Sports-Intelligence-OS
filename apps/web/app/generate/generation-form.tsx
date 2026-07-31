"use client";

import type {
  EditorialRuleSetSummary,
  GenerationRun,
  GenerationWorkflow,
  LLMProviderDescriptor,
} from "@sio/shared-types";
import {
  Check,
  ChevronRight,
  History,
  Settings2,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge, buttonClass, inputClass } from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

import {
  GenerationSourcePicker,
  type CreationSourceType,
} from "./generation-source-picker";

const lengthPresets = {
  concise: { label: "精简版", hint: "约 45 秒", minimum: 800, maximum: 950 },
  standard: {
    label: "标准版",
    hint: "约 60–75 秒",
    minimum: 1180,
    maximum: 1220,
  },
  extended: {
    label: "扩展版",
    hint: "约 75–90 秒",
    minimum: 1250,
    maximum: 1500,
  },
} as const;

type LengthPreset = keyof typeof lengthPresets;

export function GenerationForm({
  workspaceId,
  workflows,
  providers,
  ruleSets,
}: {
  workspaceId: string;
  workflows: GenerationWorkflow[];
  providers: LLMProviderDescriptor[];
  ruleSets: EditorialRuleSetSummary[];
}) {
  const router = useRouter();
  const search = useSearchParams();
  const workflow = useMemo(
    () =>
      workflows.find(
        (item) =>
          item.enabled && item.key === "sports-short-video-full-package",
      ) ?? workflows.find((item) => item.enabled),
    [workflows],
  );
  const provider = useMemo(
    () =>
      providers.find((item) => item.configured && !item.is_mock) ??
      providers.find((item) => item.configured && item.is_mock),
    [providers],
  );
  const initialType = normalizeSourceType(search.get("input_type"));
  const [inputType, setInputType] = useState<CreationSourceType>(initialType);
  const [inputId, setInputId] = useState(search.get("input_id") ?? "");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [answerWord, setAnswerWord] = useState("");
  const [creatorBrief, setCreatorBrief] = useState("");
  const [lengthPreset, setLengthPreset] = useState<LengthPreset>("standard");
  const [ruleVersionId, setRuleVersionId] = useState(
    workflow?.default_rule_set_version_id ??
      ruleSets.find((item) => item.current_version_id)?.current_version_id ??
      "",
  );
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const length = lengthPresets[lengthPreset];
  const sourceReady =
    inputType === "user_text" ? Boolean(text.trim()) : Boolean(inputId);
  const canGenerate = Boolean(
    workflow && provider && ruleVersionId && sourceReady && !busy,
  );

  async function generate() {
    if (!workflow || !provider || !canGenerate) return;
    setBusy(true);
    setStatus("正在创建内容，系统会自动整理事实、应用规则并完成质量检查…");
    try {
      const inputPayload: Record<string, unknown> = {};
      if (inputType === "user_text") {
        inputPayload.title = title.trim();
        inputPayload.text = text.trim();
        inputPayload.language = "zh-CN";
      }
      if (answerWord.trim()) {
        inputPayload.answer_word = answerWord.trim();
        inputPayload.answer_reveal_min_ratio = 0.55;
      }
      if (creatorBrief.trim()) inputPayload.creator_brief = creatorBrief.trim();
      const run = await apiRequest<GenerationRun>("/generations", {
        method: "POST",
        workspaceId,
        csrf: true,
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          workflow_id: workflow.id,
          input_type: inputType,
          input_id: inputType === "user_text" ? null : inputId,
          input_payload: inputPayload,
          rule_set_version_id: ruleVersionId,
          prompt_version_id: null,
          provider: provider.key,
          model: provider.default_model ?? "sports-content-default",
          model_config: {
            target_min_chars: length.minimum,
            target_max_chars: length.maximum,
            max_rewrites: 2,
          },
        }),
      });
      router.push(`/generations/${run.id}`);
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "内容创建失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-7 space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ["01", "选择素材", "热门视频、新闻或事件"],
          ["02", "选择规则", "决定叙事与成片标准"],
          ["03", "获得成品", "文案、标题、翻译与素材词"],
        ].map(([index, label, hint]) => (
          <div
            className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"
            key={index}
          >
            <span className="text-xs font-semibold text-cyan-400">{index}</span>
            <p className="mt-1 text-sm font-medium text-slate-100">{label}</p>
            <p className="mt-1 text-xs text-slate-500">{hint}</p>
          </div>
        ))}
      </div>

      <GenerationSourcePicker
        inputId={inputId}
        inputType={inputType}
        onInputIdChange={setInputId}
        onInputTypeChange={setInputType}
        onTextChange={setText}
        onTitleChange={setTitle}
        text={text}
        title={title}
        workspaceId={workspaceId}
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5 lg:p-6">
          <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
            02 · 成片规则
          </p>
          <h2 className="mt-2 text-xl font-semibold text-white">
            选择你希望遵循的规则预设
          </h2>
          <p className="mt-2 text-sm text-slate-400">
            内置 Prompt、模型参数和质量检查由系统管理，不需要手工编排。
          </p>

          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-300">
              规则预设
              <select
                className={inputClass}
                onChange={(event) => setRuleVersionId(event.target.value)}
                value={ruleVersionId}
              >
                {ruleSets
                  .filter((item) => item.current_version_id)
                  .map((item) => (
                    <option key={item.id} value={item.current_version_id ?? ""}>
                      {item.name}
                    </option>
                  ))}
              </select>
            </label>
            <fieldset>
              <legend className="text-sm text-slate-300">成片长度</legend>
              <div className="mt-2 grid grid-cols-3 gap-2">
                {Object.entries(lengthPresets).map(([key, item]) => (
                  <button
                    aria-pressed={lengthPreset === key}
                    className={`rounded-lg border px-2 py-2 text-left transition ${
                      lengthPreset === key
                        ? "border-cyan-700 bg-cyan-950/50"
                        : "border-slate-800 hover:border-slate-700"
                    }`}
                    key={key}
                    onClick={() => setLengthPreset(key as LengthPreset)}
                    type="button"
                  >
                    <span className="block text-xs text-slate-200">
                      {item.label}
                    </span>
                    <span className="mt-1 block text-[10px] text-slate-500">
                      {item.hint}
                    </span>
                  </button>
                ))}
              </div>
            </fieldset>
          </div>

          <details className="mt-5 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <summary className="cursor-pointer text-sm text-slate-300">
              可选调整
            </summary>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm text-slate-300">
                受保护答案词
                <input
                  className={inputClass}
                  onChange={(event) => setAnswerWord(event.target.value)}
                  placeholder="例如：运动员姓名或关键判罚"
                  value={answerWord}
                />
                <span className="text-xs text-slate-500">
                  填写后，系统会检查它不能在文案前 55% 提前泄露。
                </span>
              </label>
              <label className="grid gap-2 text-sm text-slate-300">
                补充创作重点
                <textarea
                  className="min-h-24 rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-slate-100 outline-none focus:border-cyan-500"
                  onChange={(event) => setCreatorBrief(event.target.value)}
                  placeholder="例如：重点突出最后一回合；这部分会作为不可信输入记录，不会覆盖事实规则。"
                  value={creatorBrief}
                />
              </label>
            </div>
          </details>
        </section>

        <aside className="rounded-2xl border border-cyan-900/60 bg-cyan-950/15 p-5 lg:p-6">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs font-semibold tracking-[.18em] text-cyan-400 uppercase">
              03 · 一键生成
            </p>
            <Sparkles className="text-cyan-300" size={20} />
          </div>
          <h2 className="mt-3 text-xl font-semibold text-white">
            直接获得完整内容包
          </h2>
          <ul className="mt-5 space-y-3 text-sm text-slate-300">
            {[
              "事实摘要与故事价值判断",
              "一行美式英文 TTS 与中文翻译",
              "中英文标题、搜索词和素材关键词",
              "标签、工程文件名与 QA 检查",
            ].map((item) => (
              <li className="flex gap-2" key={item}>
                <Check className="mt-0.5 shrink-0 text-emerald-400" size={15} />
                {item}
              </li>
            ))}
          </ul>

          <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-xs text-slate-400">
            {provider?.is_mock ? (
              <>
                <Badge tone="warning">Mock 测试模式</Badge>
                <p className="mt-2 leading-5">
                  当前没有可用的真实 LLM 配置，结果会明确标记为测试输出。
                </p>
                <Link
                  className="mt-2 inline-flex items-center gap-1 text-cyan-300"
                  href="/settings"
                >
                  <Settings2 size={13} /> 配置 LLM API
                </Link>
              </>
            ) : provider ? (
              <>
                <Badge tone="success">内容引擎已就绪</Badge>
                <p className="mt-2 leading-5">
                  将使用设置中心当前启用的 LLM 和内置
                  Prompt，密钥不会发送到前端。
                </p>
              </>
            ) : (
              <p className="text-rose-300">没有可用的内容生成 Provider。</p>
            )}
          </div>

          <button
            className={`${buttonClass} mt-5 w-full`}
            disabled={!canGenerate}
            onClick={generate}
            type="button"
          >
            {busy ? "正在创建…" : "立即生成内容包"}
            {!busy ? <ChevronRight size={16} /> : null}
          </button>
          {!sourceReady ? (
            <p className="mt-3 text-center text-xs text-slate-500">
              请先选择一条素材或填写自定义材料
            </p>
          ) : !ruleVersionId ? (
            <p className="mt-3 text-center text-xs text-rose-300">
              没有已发布的规则版本
            </p>
          ) : null}
          {status ? (
            <p className="mt-3 text-sm leading-6 text-slate-300" role="status">
              {status}
            </p>
          ) : null}
          <Link
            className="mt-5 flex items-center justify-center gap-2 text-sm text-slate-400 hover:text-slate-200"
            href="/generations"
          >
            <History size={15} /> 查看历史内容
          </Link>
        </aside>
      </div>
    </div>
  );
}

function normalizeSourceType(value: string | null): CreationSourceType {
  return value === "news" ||
    value === "event" ||
    value === "content" ||
    value === "user_text"
    ? value
    : "content";
}
