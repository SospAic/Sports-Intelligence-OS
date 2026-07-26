import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getPrompts } from "@/lib/generation";

export default async function PromptsPage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const prompts = await getPrompts(workspace.workspace_id);
  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-6xl">
        <p className="text-xs font-semibold tracking-[0.24em] text-cyan-300 uppercase">
          Prompt Registry
        </p>
        <h1 className="mt-3 text-3xl font-semibold text-white">Prompt 中心</h1>
        <p className="mt-2 text-sm text-slate-400">
          Prompt 正文、变量 Schema 和模型默认参数均来自数据库版本，不在 Python
          业务代码中硬编码。
        </p>
        {!prompts ? (
          <p className="mt-8 rounded-xl border border-rose-900/60 p-4 text-sm text-rose-200">
            无法读取 Prompt 集合。
          </p>
        ) : prompts.items.length === 0 ? (
          <p className="mt-8 rounded-xl border border-slate-800 p-8 text-sm text-slate-400">
            尚无 Prompt。请在导入并发布 7.9 规则后执行 `make seed-generation`。
          </p>
        ) : (
          <div className="mt-8 grid gap-4 md:grid-cols-2">
            {prompts.items.map((item) => (
              <Link
                className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 hover:border-cyan-900"
                href={`/prompts/${item.id}`}
                key={item.id}
              >
                <div className="flex items-center justify-between gap-4">
                  <span className="font-mono text-xs text-cyan-300">
                    {item.key}
                  </span>
                  <span className="text-xs text-slate-500">{item.status}</span>
                </div>
                <h2 className="mt-3 text-lg font-semibold text-white">
                  {item.name}
                </h2>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-400">
                  {item.description}
                </p>
                <p className="mt-4 text-xs text-slate-500">
                  {item.version_count} 个版本 · 当前{" "}
                  {item.current_version_id ? "已发布" : "未发布"}
                </p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
