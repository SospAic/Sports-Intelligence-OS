import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getWorkflows } from "@/lib/generation";

export default async function WorkflowsPage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const workflows = await getWorkflows(workspace.workspace_id);
  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-6xl">
        <p className="text-xs font-semibold tracking-[0.24em] text-cyan-300 uppercase">
          Workflow Registry
        </p>
        <h1 className="mt-3 text-3xl font-semibold text-white">生成工作流</h1>
        {!workflows ? (
          <p className="mt-8 rounded-xl border border-rose-900/60 p-4 text-sm text-rose-200">
            无法读取工作流。
          </p>
        ) : (
          <div className="mt-8 space-y-5">
            {workflows.map((workflow) => (
              <article
                className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6"
                key={workflow.id}
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="font-mono text-xs text-cyan-300">
                      {workflow.key}
                    </p>
                    <h2 className="mt-2 text-xl font-semibold text-white">
                      {workflow.name}
                    </h2>
                    <p className="mt-2 text-sm text-slate-400">
                      {workflow.description}
                    </p>
                  </div>
                  <span className="rounded-full border border-slate-700 px-3 py-1 text-xs">
                    {workflow.enabled ? "已启用" : "已停用"}
                  </span>
                </div>
                <ol className="mt-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                  {workflow.steps.map((step) => (
                    <li
                      className="rounded-lg border border-slate-800 p-3"
                      key={step.key}
                    >
                      <span className="text-[10px] text-slate-600">
                        {step.sort_order}/10
                      </span>
                      <p className="mt-1 text-xs text-slate-300">{step.name}</p>
                    </li>
                  ))}
                </ol>
                <p className="mt-5 text-xs text-slate-500">
                  默认规则 {workflow.default_rule_set_version_id ?? "未配置"} ·
                  默认 Prompt {workflow.default_prompt_version_id ?? "未配置"}
                </p>
              </article>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
