import type { GenerationRun } from "@sio/shared-types";

// ── A 组：原有字段 ────────────────────────────────────────────────────────────
export type GenerationOutputKeyA =
  | "event_fact_summary"
  | "fact_sources"
  | "story_value"
  | "tts_en"
  | "translation_zh"
  | "video_title_en"
  | "video_title_zh"
  | "search_keywords"
  | "material_keywords"
  | "tags"
  | "project_filename"
  | "qa_report"
  | "used_rules"
  | "rewrite_reasons";

// ── B 组：7.9 完整输出包新增核心字段 ─────────────────────────────────────────
export type GenerationOutputKeyB =
  | "spoken_char_count"
  | "event_identity"
  | "story_format"
  | "story_format_reason"
  | "central_question"
  | "selected_hook"
  | "cmssml"
  | "ev3"
  | "story_architecture"
  | "lcr_enabled"
  | "lcr_reason"
  | "hook_candidates"
  | "answer_word_map"
  | "reaction_relay"
  | "evidence_rewards"
  | "exclusion_ladder"
  | "dialogue_notes";

// ── C 组：ambiguous 可选字段（原文不完整，最大努力生成） ──────────────────────
export type GenerationOutputKeyC =
  | "audio_performance_map"
  | "tts_settings"
  | "video_material_plan"
  | "edit_map"
  | "caption_map"
  | "original_audio_plan"
  | "srt_output";

export type GenerationOutputKey =
  | GenerationOutputKeyA
  | GenerationOutputKeyB
  | GenerationOutputKeyC;

export const outputLabels: Record<GenerationOutputKey, string> = {
  // A 组
  event_fact_summary: "事件事实摘要",
  fact_sources: "事实来源",
  story_value: "故事价值",
  tts_en: "英文 TTS 文案",
  translation_zh: "中文翻译",
  video_title_en: "英文视频标题",
  video_title_zh: "中文视频标题",
  search_keywords: "搜索关键词",
  material_keywords: "视频素材关键词",
  tags: "发布标签",
  project_filename: "工程文件名",
  qa_report: "质量检查",
  used_rules: "使用规则",
  rewrite_reasons: "重写原因",
  // B 组
  spoken_char_count: "精确字符数",
  event_identity: "事件精确识别",
  story_format: "主故事格式",
  story_format_reason: "格式选择原因",
  central_question: "中心悬念",
  selected_hook: "选定 Hook",
  cmssml: "CMSSML（单行）",
  ev3: "EV3（单行）",
  story_architecture: "故事架构",
  lcr_enabled: "LCR 是否启用",
  lcr_reason: "LCR 决策原因",
  hook_candidates: "Hook 候选列表",
  answer_word_map: "答案词与泄露映射",
  reaction_relay: "Reaction Relay 结构",
  evidence_rewards: "证据奖励结构",
  exclusion_ladder: "合理解释排除列表",
  dialogue_notes: "对话与心理说明",
  // C 组
  audio_performance_map: "Audio Performance Map",
  tts_settings: "TTS 设置建议",
  video_material_plan: "视频素材逐 Beat 计划",
  edit_map: "剪辑 Map",
  caption_map: "字幕 Map",
  original_audio_plan: "原声使用计划",
  srt_output: "SRT 字幕",
};

export function outputText(
  output: Record<string, unknown>,
  key: GenerationOutputKey,
): string {
  const value = output[key];
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) return "";
  return JSON.stringify(value, null, 2);
}

export function outputList(
  output: Record<string, unknown>,
  key: GenerationOutputKey,
): string[] {
  const value = output[key];
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        typeof item === "string" ? item : JSON.stringify(item, null, 2),
      )
      .filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(/[,，\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return [];
}

export function generationSourceTitle(run: GenerationRun): string {
  for (const key of ["title", "normalized_title", "name"] as const) {
    const value = run.input_payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return (
    {
      content: "平台热门视频",
      news: "体育热点新闻",
      event: "体育热点事件",
      user_text: "自定义创作材料",
    }[run.input_type] ?? "内容素材"
  );
}

export function generationStatusLabel(status: GenerationRun["status"]): string {
  return {
    queued: "等待生成",
    running: "正在生成",
    completed: "内容已完成",
    failed: "生成失败",
    cancelled: "已取消",
  }[status];
}

export function generationInputTypeLabel(value: string): string {
  return (
    {
      content: "热门视频",
      news: "热点新闻",
      event: "聚合事件",
      user_text: "自定义材料",
    }[value] ?? value
  );
}

export function generationVerificationLabel(value: string): string {
  return (
    {
      verified: "已核实",
      partially_verified: "部分核实",
      verification_incomplete: "核实未完成",
      unverified: "未核实",
    }[value] ?? value
  );
}

export function generationProgress(run: GenerationRun): {
  completed: number;
  total: number;
  percent: number;
  current: string;
} {
  const total = run.steps.length || 10;
  const completed = run.steps.filter(
    (step) => step.status === "completed" || step.status === "skipped",
  ).length;
  const percent =
    run.status === "completed"
      ? 100
      : Math.min(95, Math.round((completed / total) * 100));
  const current =
    run.status === "queued"
      ? "等待内容引擎"
      : run.status === "completed"
        ? "内容包已完成"
        : run.status === "failed"
          ? "生成流程中断"
          : friendlyStep(run.current_step);
  return { completed, total, percent, current };
}

function friendlyStep(step: string | null): string {
  if (!step) return "正在准备素材";
  if (["research_input", "normalize_facts", "build_timeline"].includes(step)) {
    return "正在整理事实与时间线";
  }
  if (["story_qualification", "apply_rules"].includes(step)) {
    return "正在判断故事价值并应用规则";
  }
  if (["generate_draft", "editorial_review"].includes(step)) {
    return "正在生成和编辑文案";
  }
  if (["qa_validation", "automatic_rewrite"].includes(step)) {
    return "正在检查并优化成片内容";
  }
  return "正在整理最终内容包";
}
