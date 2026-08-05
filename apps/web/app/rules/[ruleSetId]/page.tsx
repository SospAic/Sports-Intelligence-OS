import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getRuleSetDetail } from "@/lib/rules";
import { VersionActions } from "./version-actions";
import { RuleExportButtons } from "./rule-export-buttons";
import { BackButton } from "@/components/back-button";

export default async function RuleSetPage({
  params,
}: {
  params: Promise<{ ruleSetId: string }>;
}) {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) notFound();
  const { ruleSetId } = await params;
  const ruleSet = await getRuleSetDetail(workspace.workspace_id, ruleSetId);
  if (!ruleSet) notFound();

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-6xl">
        <BackButton label="返回规则中心" />
        <header className="mt-6 flex flex-col gap-5 border-b border-slate-800 pb-7 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs text-cyan-300">{ruleSet.key}</p>
            <h1 className="mt-2 text-3xl font-semibold text-white">
              {ruleSet.name}
            </h1>
            <p className="mt-2 text-sm text-slate-400">{ruleSet.description}</p>
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            <Link
              className="rounded-lg border border-slate-700 px-3 py-2 text-slate-200"
              href={`/rules/${ruleSet.id}/compare`}
            >
              版本对比
            </Link>
            <Link
              className="rounded-lg bg-cyan-300 px-3 py-2 font-semibold text-slate-950"
              href={`/rules/${ruleSet.id}/edit`}
            >
              打开编辑器
            </Link>
          </div>
        </header>

        <section className="mt-8 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/70">
          <div className="flex items-center justify-between border-b border-slate-800 p-5">
            <div>
              <h2 className="font-semibold text-white">版本记录</h2>
              <p className="mt-1 text-xs text-slate-500">
                已发布版本不可修改；编辑时自动复制为新草稿。
              </p>
            </div>
            <VersionActions
              currentVersionId={ruleSet.current_version_id}
              ruleSetId={ruleSet.id}
              workspaceId={workspace.workspace_id}
            />
          </div>
          <ul className="divide-y divide-slate-800">
            {ruleSet.versions.map((version) => (
              <li
                className="grid gap-4 p-5 md:grid-cols-[1fr_auto]"
                key={version.id}
              >
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <Link
                      className="font-medium text-white hover:text-cyan-200"
                      href={`/rules/${ruleSet.id}/versions/${version.id}`}
                    >
                      {version.version}
                    </Link>
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs ${
                        version.status === "published"
                          ? "border-emerald-900 text-emerald-200"
                          : "border-amber-900 text-amber-200"
                      }`}
                    >
                      {version.status}
                    </span>
                    {ruleSet.current_version_id === version.id ? (
                      <span className="text-xs text-cyan-300">当前生效</span>
                    ) : null}
                  </div>
                  <p className="mt-2 text-sm text-slate-400">
                    {version.changelog ?? "未填写变更说明"}
                  </p>
                  <p className="mt-2 font-mono text-xs text-slate-600">
                    SHA-256 {version.source_hash}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <RuleExportButtons
                    ruleSetId={ruleSet.id}
                    versionId={version.id}
                    workspaceId={workspace.workspace_id}
                  />
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
