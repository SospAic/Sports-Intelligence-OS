import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import {
  getGenerationRuleSets,
  getLLMProviders,
  getPrompts,
  getWorkflows,
} from "@/lib/generation";
import { GenerationForm } from "./generation-form";

export default async function GeneratePage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const [workflows, providers, prompts, ruleSets] = await Promise.all([
    getWorkflows(workspace.workspace_id),
    getLLMProviders(workspace.workspace_id),
    getPrompts(workspace.workspace_id),
    getGenerationRuleSets(workspace.workspace_id),
  ]);

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <p className="text-xs font-semibold tracking-[0.24em] text-cyan-300 uppercase">
          Generation Studio
        </p>
        <h1 className="mt-3 text-3xl font-semibold text-white">内容生成</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          输入会先冻结，再依次执行
          Research、事实、时间线、资格判断、规则编译、草稿、编辑审查、QA、重写和最终格式化。
        </p>
        {!workflows || !providers || !prompts || !ruleSets ? (
          <div className="mt-8 rounded-2xl border border-rose-900/60 bg-rose-950/20 p-5 text-sm text-rose-200">
            无法读取生成配置。请确认 API 可用，并已执行规则导入和 generation
            seed。
          </div>
        ) : (
          <GenerationForm
            prompts={prompts.items}
            providers={providers}
            ruleSets={ruleSets.items}
            workflows={workflows}
            workspaceId={workspace.workspace_id}
          />
        )}
      </div>
    </main>
  );
}
