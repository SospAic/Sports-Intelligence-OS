"use client";

import { useState } from "react";

import { apiRequest } from "@/lib/browser-api";

type SimulationRule = {
  rule_id: string;
  key: string;
  title: string;
  priority: number;
  applies: boolean;
  reason: string;
  execution_state: "not_executed";
};

type Simulation = {
  id: string;
  historical_at: string | null;
  rules: SimulationRule[];
  applicable_count: number;
  skipped_count: number;
  created_at: string;
};

type SimulationPage = { items: Simulation[]; total: number };

export function RuleSimulator({
  workspaceId,
  ruleSetId,
  versionId,
}: {
  workspaceId: string;
  ruleSetId: string;
  versionId: string;
}) {
  const [sport, setSport] = useState("");
  const [storyType, setStoryType] = useState("");
  const [outputType, setOutputType] = useState("");
  const [text, setText] = useState("");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [history, setHistory] = useState<Simulation[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const basePath = `/rules/${ruleSetId}/versions/${versionId}`;

  async function runSimulation() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await apiRequest<Simulation>(`${basePath}/simulate`, {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({
          context: {
            sport: sport.trim() || null,
            story_type: storyType.trim() || null,
            output_type: outputType.trim() || null,
            text: text.trim() || null,
            facts: {},
          },
        }),
      });
      setSimulation(result);
      setMessage("模拟已保存；结果仅表示规则适用性，未执行模型或 QA。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "模拟失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadHistory() {
    setBusy(true);
    try {
      const result = await apiRequest<SimulationPage>(`${basePath}/simulations`, {
        workspaceId,
      });
      setHistory(result.items);
      setMessage(`已加载 ${result.total} 条历史模拟`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "历史模拟加载失败");
    } finally {
      setBusy(false);
    }
  }

  async function submitFeedback(rule: SimulationRule, verdict: "pass" | "fail" | "uncertain") {
    if (!simulation) return;
    try {
      await apiRequest(
        `${basePath}/simulations/${simulation.id}/rules/${rule.rule_id}/feedback`,
        {
          method: "POST",
          workspaceId,
          csrf: true,
          body: JSON.stringify({ verdict }),
        },
      );
      setMessage(`已记录 ${rule.key} 的人工反馈：${verdict}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "反馈提交失败");
    }
  }

  return (
    <section className="mt-8 rounded-2xl border border-cyan-900/70 bg-slate-950/70 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold text-white">规则模拟与历史回放</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
            依据明确的运动项目、故事类型和输出类型筛选规则，保留版本哈希和输入上下文。
            这是可审计的适用性预览，不会调用模型、写入生成运行或声称事实/QA 已通过。
          </p>
        </div>
        <button
          className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-200"
          disabled={busy}
          onClick={loadHistory}
          type="button"
        >
          查看历史
        </button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <label className="text-xs text-slate-400">
          运动项目
          <input
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            onChange={(event) => setSport(event.target.value)}
            placeholder="如 basketball"
            value={sport}
          />
        </label>
        <label className="text-xs text-slate-400">
          故事类型
          <input
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            onChange={(event) => setStoryType(event.target.value)}
            placeholder="如 match_recap"
            value={storyType}
          />
        </label>
        <label className="text-xs text-slate-400">
          输出类型
          <input
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            onChange={(event) => setOutputType(event.target.value)}
            placeholder="如 tts"
            value={outputType}
          />
        </label>
        <label className="text-xs text-slate-400 md:col-span-1">
          素材摘要
          <input
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            onChange={(event) => setText(event.target.value)}
            placeholder="可选，仅保存供复核"
            value={text}
          />
        </label>
      </div>
      <button
        className="mt-4 rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
        disabled={busy}
        onClick={runSimulation}
        type="button"
      >
        {busy ? "处理中…" : "运行模拟"}
      </button>
      {message ? <p className="mt-3 text-xs text-cyan-200">{message}</p> : null}
      {simulation ? (
        <div className="mt-5">
          <div className="flex flex-wrap gap-3 text-xs text-slate-400">
            <span>适用 {simulation.applicable_count}</span>
            <span>跳过 {simulation.skipped_count}</span>
            <span>记录于 {new Date(simulation.created_at).toLocaleString("zh-CN")}</span>
          </div>
          <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-slate-800">
            {simulation.rules.slice(0, 80).map((rule) => (
              <div
                className="grid gap-2 border-b border-slate-800 px-3 py-2 text-xs last:border-b-0 md:grid-cols-[auto_1fr_auto] md:items-center"
                key={rule.rule_id}
              >
                <span className={rule.applies ? "text-emerald-300" : "text-slate-500"}>
                  {rule.applies ? "适用" : "跳过"}
                </span>
                <span className="text-slate-300">
                  <strong className="mr-2 text-cyan-200">{rule.key}</strong>
                  {rule.reason}
                </span>
                {rule.applies ? (
                  <span className="flex gap-1">
                    {(["pass", "fail", "uncertain"] as const).map((verdict) => (
                      <button
                        className="rounded border border-slate-700 px-2 py-1 text-slate-400 hover:text-white"
                        key={verdict}
                        onClick={() => submitFeedback(rule, verdict)}
                        type="button"
                      >
                        {verdict}
                      </button>
                    ))}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {history.length > 0 ? (
        <div className="mt-4 text-xs text-slate-500">
          最近记录：{history.map((item) => item.id.slice(0, 8)).join(" · ")}
        </div>
      ) : null}
    </section>
  );
}
