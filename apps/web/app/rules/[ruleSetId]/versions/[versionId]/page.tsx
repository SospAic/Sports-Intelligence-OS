import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getRuleTree, getRuleVersion } from "@/lib/rules";
import { RuleVersionViewer } from "./rule-version-viewer";
import { VersionLifecycle } from "./version-lifecycle";

export default async function RuleVersionPage({
  params,
}: {
  params: Promise<{ ruleSetId: string; versionId: string }>;
}) {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) notFound();
  const { ruleSetId, versionId } = await params;
  const [version, tree] = await Promise.all([
    getRuleVersion(workspace.workspace_id, ruleSetId, versionId),
    getRuleTree(workspace.workspace_id, ruleSetId, versionId),
  ]);
  if (!version || !tree) notFound();

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <Link className="text-sm text-cyan-300" href={`/rules/${ruleSetId}`}>
          ← 返回版本列表
        </Link>
        <div className="mt-6 flex flex-col gap-3 border-b border-slate-800 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold text-white">
              规则版本 {version.version}
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              {version.section_count} 个章节 · {version.rule_count} 条规则 ·{" "}
              {version.status}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <VersionLifecycle
              ruleSetId={ruleSetId}
              status={version.status}
              versionId={versionId}
              workspaceId={workspace.workspace_id}
            />
            <Link
              className="rounded-lg border border-cyan-800 px-3 py-2 text-sm text-cyan-200"
              href={`/rules/${ruleSetId}/edit?version=${versionId}`}
            >
              编辑此版本
            </Link>
          </div>
        </div>
        <RuleVersionViewer
          ruleSetId={ruleSetId}
          tree={tree}
          version={version}
          versionId={versionId}
          workspaceId={workspace.workspace_id}
        />
      </div>
    </main>
  );
}
