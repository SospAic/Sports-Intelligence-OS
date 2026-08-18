import Link from "next/link";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { getGenerations } from "@/lib/generation";
import {
  generationInputTypeLabel,
  generationSourceTitle,
  generationStatusLabel,
  generationVerificationLabel,
} from "@/lib/generation-presentation";

export default async function GenerationsPage() {
  const currentUser = await getCurrentUser();
  if (!currentUser) redirect("/login");
  const workspace = currentUser.memberships[0];
  if (!workspace) redirect("/dashboard");
  const runs = await getGenerations(workspace.workspace_id);

  return (
    <main className="min-h-screen px-5 py-8 lg:px-10">
      <div className="mx-auto max-w-7xl">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-[0.24em] text-cyan-300 uppercase">
              Content Library
            </p>
            <h1 className="mt-3 text-3xl font-semibold text-white">
              内容成品库
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              查看每次素材生成的状态与最终内容；Prompt
              和模型参数保留在审计信息中。
            </p>
          </div>
          <Link
            className="rounded-lg bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950"
            href="/generate"
          >
            创建内容
          </Link>
        </div>
        {!runs ? (
          <p className="mt-8 rounded-xl border border-rose-900/60 p-4 text-sm text-rose-200">
            无法读取生成记录，请稍后重试。
          </p>
        ) : runs.items.length === 0 ? (
          <p className="mt-8 rounded-xl border border-slate-800 p-8 text-center text-sm text-slate-400">
            尚无内容成品。选择一条热门视频或新闻开始创作。
          </p>
        ) : (
          <div className="mt-8 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/70">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-5 py-3">素材</th>
                  <th className="px-5 py-3">来源类型</th>
                  <th className="px-5 py-3">状态</th>
                  <th className="px-5 py-3">核实</th>
                  <th className="px-5 py-3">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {runs.items.map((run) => (
                  <tr className="hover:bg-slate-900/70" key={run.id}>
                    <td className="max-w-xl px-5 py-4">
                      <Link
                        className="line-clamp-2 font-medium text-cyan-300"
                        href={`/generations/${run.id}`}
                      >
                        {generationSourceTitle(run)}
                      </Link>
                    </td>
                    <td className="px-5 py-4 text-slate-300">
                      {generationInputTypeLabel(run.input_type)}
                    </td>
                    <td className="px-5 py-4">
                      <span className="rounded-full border border-slate-700 px-2.5 py-1 text-xs">
                        {generationStatusLabel(run.status)}
                      </span>
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-400">
                      {generationVerificationLabel(run.verification_status)}
                    </td>
                    <td className="whitespace-nowrap px-5 py-4 text-xs text-slate-500">
                      {new Date(run.created_at).toLocaleString("zh-CN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
