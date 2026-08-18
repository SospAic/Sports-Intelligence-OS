import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { BackButton } from "@/components/back-button";
import { RuleImportForm } from "./rule-import-form";

export default async function RuleImportPage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/rules");

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-4xl">
        <BackButton label="返回规则中心" />
        <h1 className="mt-6 text-3xl font-semibold text-white">导入规则</h1>
        <p className="mt-2 text-sm text-slate-400">
          TXT 将按 UTF-8 原文解析；JSON 必须符合导出 schema，并通过原文 SHA-256
          校验。
        </p>
        <RuleImportForm workspaceId={workspace.workspace_id} />
      </div>
    </main>
  );
}
