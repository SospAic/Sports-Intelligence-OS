import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getRuleSetDetail, getRuleTree } from "@/lib/rules";
import { RuleEditor } from "./rule-editor";

export default async function RuleEditPage({
  params,
  searchParams,
}: {
  params: Promise<{ ruleSetId: string }>;
  searchParams: Promise<{ version?: string }>;
}) {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) notFound();
  const { ruleSetId } = await params;
  const query = await searchParams;
  const ruleSet = await getRuleSetDetail(workspace.workspace_id, ruleSetId);
  if (!ruleSet) notFound();
  const versionId =
    query.version ??
    ruleSet.versions.find((version) => version.status === "draft")?.id ??
    ruleSet.current_version_id;
  if (!versionId) redirect("/rules/import");
  const tree = await getRuleTree(workspace.workspace_id, ruleSetId, versionId);
  if (!tree) notFound();

  return (
    <main className="min-h-screen px-4 py-6 lg:px-6">
      <div className="mx-auto max-w-[1800px]">
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-800 pb-5">
          <div>
            <Link
              className="text-sm text-cyan-300"
              href={`/rules/${ruleSetId}`}
            >
              ← 返回版本列表
            </Link>
            <h1 className="mt-3 text-2xl font-semibold text-white">
              规则可视化编辑器
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              {tree.version.version} · {tree.version.status} ·{" "}
              {tree.total_rules} 条规则
            </p>
          </div>
          <div className="flex gap-2 text-xs">
            {ruleSet.versions.map((version) => (
              <Link
                className={`rounded border px-2.5 py-1.5 ${version.id === versionId ? "border-cyan-600 text-cyan-200" : "border-slate-700 text-slate-400"}`}
                href={`/rules/${ruleSetId}/edit?version=${version.id}`}
                key={version.id}
              >
                {version.version}
              </Link>
            ))}
          </div>
        </div>
        <RuleEditor
          ruleSetId={ruleSetId}
          tree={tree}
          workspaceId={workspace.workspace_id}
        />
      </div>
    </main>
  );
}
