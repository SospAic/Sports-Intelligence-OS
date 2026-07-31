import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import {
  getGenerationRuleSets,
  getLLMProviders,
  getWorkflows,
} from "@/lib/generation";
import { GenerationForm } from "./generation-form";

export default async function GeneratePage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const [workflows, providers, ruleSets] = await Promise.all([
    getWorkflows(workspace.workspace_id),
    getLLMProviders(workspace.workspace_id),
    getGenerationRuleSets(workspace.workspace_id),
  ]);

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <p className="text-xs font-semibold tracking-[0.24em] text-cyan-300 uppercase">
          Content Creator
        </p>
        <h1 className="mt-3 text-3xl font-semibold text-white">一键内容创作</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          选择一条热门视频、新闻或事件，再选择成片规则。系统会调用已配置的 LLM
          和内置 Prompt，直接生成可使用的体育短视频内容包。
        </p>
        {!workflows || !providers || !ruleSets ? (
          <div className="mt-8 rounded-2xl border border-rose-900/60 bg-rose-950/20 p-5 text-sm text-rose-200">
            无法读取内容创作配置。请确认 API
            可用，并已导入规则和初始化内置内容模板。
          </div>
        ) : (
          <GenerationForm
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
