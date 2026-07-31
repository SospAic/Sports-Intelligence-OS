import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getRuleSets } from "@/lib/rules";

export default async function RulesPage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  const ruleSets = workspace ? await getRuleSets(workspace.workspace_id) : null;

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-4 border-b border-slate-800 pb-6 md:flex-row md:items-end md:justify-between">
          <div>
            <Link className="text-xs text-cyan-300" href="/dashboard">
              ← 返回控制台
            </Link>
            <p className="mt-5 text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
              Editorial Knowledge
            </p>
            <h1 className="mt-2 text-3xl font-semibold text-white">
              7.9 规则中心
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              原文、结构化规则、版本状态和修改历史均由后端持久化，不是静态展示。
            </p>
          </div>
          <Link
            className="rounded-lg bg-cyan-300 px-4 py-2.5 text-sm font-semibold text-slate-950"
            href="/rules/import"
          >
            导入规则
          </Link>
        </header>

        {!ruleSets ? (
          <section className="mt-8 rounded-2xl border border-rose-900/60 bg-rose-950/20 p-6 text-rose-200">
            无法读取规则数据，请检查 API 或工作区权限后重试。
          </section>
        ) : ruleSets.items.length === 0 ? (
          <section className="mt-8 rounded-2xl border border-slate-800 bg-slate-950/60 p-10 text-center">
            <h2 className="text-lg font-medium text-white">尚未导入规则集合</h2>
            <p className="mt-2 text-sm text-slate-400">
              请导入完整 TXT 原文或经过哈希校验的 JSON 规则包。
            </p>
          </section>
        ) : (
          <section className="mt-8 grid gap-4 lg:grid-cols-2">
            {ruleSets.items.map((ruleSet) => (
              <article
                className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6"
                key={ruleSet.id}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-xs text-cyan-300">{ruleSet.key}</p>
                    <h2 className="mt-2 text-xl font-semibold text-white">
                      {ruleSet.name}
                    </h2>
                  </div>
                  <span className="rounded-full border border-emerald-900 bg-emerald-950/40 px-2.5 py-1 text-xs text-emerald-200">
                    {ruleSet.status}
                  </span>
                </div>
                <p className="mt-4 line-clamp-2 text-sm text-slate-400">
                  {ruleSet.description ?? "暂无说明"}
                </p>
                <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-300">
                  <span className="rounded border border-slate-700 px-2 py-1">
                    {ruleSet.version_count} 个版本
                  </span>
                  <span className="rounded border border-slate-700 px-2 py-1">
                    {ruleSet.draft_count} 个草稿
                  </span>
                  {ruleSet.tags.map((tag) => (
                    <span className="rounded bg-slate-900 px-2 py-1" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="mt-6 flex gap-3 text-sm">
                  <Link
                    className="rounded-lg border border-cyan-800 px-3 py-2 text-cyan-200"
                    href={`/rules/${ruleSet.id}`}
                  >
                    查看版本
                  </Link>
                  <Link
                    className="rounded-lg border border-slate-700 px-3 py-2 text-slate-200"
                    href={`/rules/${ruleSet.id}/edit`}
                  >
                    打开编辑器
                  </Link>
                </div>
              </article>
            ))}
          </section>
        )}
      </div>
    </main>
  );
}
