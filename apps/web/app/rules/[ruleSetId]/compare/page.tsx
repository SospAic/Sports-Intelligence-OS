import { notFound, redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getRuleSetDetail } from "@/lib/rules";
import { BackButton } from "@/components/back-button";
import { RuleCompare } from "./rule-compare";

export default async function RuleComparePage({
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
        <BackButton label="返回版本列表" />
        <h1 className="mt-6 text-3xl font-semibold text-white">版本差异对比</h1>
        <p className="mt-2 text-sm text-slate-400">
          按稳定规则 key 比较新增、删除以及字段级修改。
        </p>
        <RuleCompare
          ruleSetId={ruleSetId}
          versions={ruleSet.versions}
          workspaceId={workspace.workspace_id}
        />
      </div>
    </main>
  );
}
