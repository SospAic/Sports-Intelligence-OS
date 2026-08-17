"use client";

import type { AccountRecord, AccountRecordPage } from "@sio/shared-types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, Trash2, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Panel,
  StatePanel,
  buttonClass,
  inputClass,
  secondaryButtonClass,
} from "@/components/ui";
import { apiRequest } from "@/lib/browser-api";

type WorkspaceMember = {
  id: string;
  display_name: string;
  email: string;
  role: "owner" | "admin" | "editor" | "analyst" | "viewer";
};

type AccountGrant = {
  id: string;
  account_id: string;
  user_id: string;
  permission: "viewer" | "editor";
  created_at: string;
  updated_at: string;
};

export function AccountAccessPanel({ workspaceId }: { workspaceId: string }) {
  const { notify } = useToast();
  const queryClient = useQueryClient();
  const [accountId, setAccountId] = useState("");
  const [userId, setUserId] = useState("");
  const [permission, setPermission] = useState<AccountGrant["permission"]>("viewer");
  const [pending, setPending] = useState(false);

  const accounts = useQuery({
    queryKey: ["account-access-accounts", workspaceId],
    queryFn: () =>
      apiRequest<AccountRecordPage>(
        "/accounts?page=1&page_size=100&is_active=true",
        { workspaceId },
      ),
  });
  const members = useQuery({
    queryKey: ["account-access-members", workspaceId],
    queryFn: () => apiRequest<WorkspaceMember[]>("/workspace-members", { workspaceId }),
  });
  const grants = useQuery({
    queryKey: ["workspace-account-grants", workspaceId],
    queryFn: () => apiRequest<AccountGrant[]>("/workspace-account-grants", { workspaceId }),
  });

  const accountById = new Map(
    (accounts.data?.items ?? []).map((account: AccountRecord) => [account.id, account]),
  );
  const memberById = new Map(
    (members.data ?? []).map((member) => [member.id, member]),
  );
  const grantableMembers = (members.data ?? []).filter(
    (member) => !["owner", "admin"].includes(member.role),
  );

  async function createGrant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accountId || !userId) {
      notify("请选择账号和成员", "error");
      return;
    }
    setPending(true);
    try {
      await apiRequest("/workspace-account-grants", {
        method: "POST",
        workspaceId,
        csrf: true,
        body: JSON.stringify({ account_id: accountId, user_id: userId, permission }),
      });
      notify("账号授权已保存");
      setAccountId("");
      setUserId("");
      setPermission("viewer");
      await queryClient.invalidateQueries({ queryKey: ["workspace-account-grants", workspaceId] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "账号授权保存失败", "error");
    } finally {
      setPending(false);
    }
  }

  async function revokeGrant(grant: AccountGrant) {
    const member = memberById.get(grant.user_id);
    const account = accountById.get(grant.account_id);
    if (!window.confirm(`确定撤销 ${member?.display_name ?? grant.user_id} 对 ${account?.display_name ?? "该账号"} 的授权？`)) {
      return;
    }
    setPending(true);
    try {
      await apiRequest<void>(`/workspace-account-grants/${grant.id}`, {
        method: "DELETE",
        workspaceId,
        csrf: true,
      });
      notify("账号授权已撤销");
      await queryClient.invalidateQueries({ queryKey: ["workspace-account-grants", workspaceId] });
    } catch (error) {
      notify(error instanceof Error ? error.message : "账号授权撤销失败", "error");
    } finally {
      setPending(false);
    }
  }

  if (accounts.error || members.error || grants.error) {
    const error = accounts.error ?? members.error ?? grants.error;
    return (
      <Panel className="p-5">
        <StatePanel
          type="error"
          title="账号授权数据加载失败"
          detail={error instanceof Error ? error.message : "请稍后重试"}
          onRetry={() => {
            void accounts.refetch();
            void members.refetch();
            void grants.refetch();
          }}
        />
      </Panel>
    );
  }

  if (accounts.isLoading || members.isLoading || grants.isLoading) {
    return <Panel className="p-5 text-sm text-slate-500">正在加载账号授权…</Panel>;
  }

  return (
    <div className="space-y-5">
      <Panel className="p-5">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 text-cyan-300" size={20} />
          <div>
            <h2 className="font-medium text-white">账号级访问授权</h2>
            <p className="mt-1 text-sm leading-6 text-slate-400">
              Owner / Admin 默认可访问全部账号；为普通成员建立第一条授权后，该成员的账号与作品读取范围会收敛到已授权账号。授权动作会写入审计日志。
            </p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Badge tone="info">viewer：读取</Badge>
              <Badge tone="success">editor：读取与编辑</Badge>
              <Badge tone="neutral">频道级与发布资源权限另行建模</Badge>
            </div>
          </div>
        </div>
      </Panel>

      <Panel className="p-5">
        <div className="mb-4 flex items-center gap-2">
          <UserRound className="text-slate-400" size={17} />
          <h2 className="font-medium text-white">新增或更新授权</h2>
        </div>
        <form className="grid gap-3 md:grid-cols-[1.3fr_1.3fr_0.8fr_auto]" onSubmit={createGrant}>
          <select className={inputClass} value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="">选择账号</option>
            {(accounts.data?.items ?? []).map((account) => (
              <option key={account.id} value={account.id}>
                {account.display_name} · {account.platform.name}
              </option>
            ))}
          </select>
          <select className={inputClass} value={userId} onChange={(event) => setUserId(event.target.value)}>
            <option value="">选择成员</option>
            {grantableMembers.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_name} · {member.email}
              </option>
            ))}
          </select>
          <select className={inputClass} value={permission} onChange={(event) => setPermission(event.target.value as AccountGrant["permission"]) }>
            <option value="viewer">viewer · 读取</option>
            <option value="editor">editor · 读取与编辑</option>
          </select>
          <button className={buttonClass} disabled={pending || !accounts.data?.items.length || !grantableMembers.length} type="submit">
            保存授权
          </button>
        </form>
        {!grantableMembers.length && (
          <p className="mt-3 text-xs text-amber-300">当前没有可授权的普通成员；Owner / Admin 不需要账号级授权。</p>
        )}
        {(accounts.data?.total ?? 0) > 100 && (
          <p className="mt-3 text-xs text-amber-300">当前面板显示前 100 个启用账号，请在账号列表中确认完整范围。</p>
        )}
      </Panel>

      <Panel className="overflow-hidden">
        <div className="border-b border-slate-800 px-5 py-4">
          <h2 className="font-medium text-white">当前授权（{grants.data?.length ?? 0}）</h2>
        </div>
        {!grants.data?.length ? (
          <div className="p-5 text-sm text-slate-500">暂无账号级授权。普通成员仍按工作区兼容策略读取全部账号。</div>
        ) : (
          <div className="divide-y divide-slate-800">
            {grants.data.map((grant) => {
              const account = accountById.get(grant.account_id);
              const member = memberById.get(grant.user_id);
              return (
                <div className="grid gap-3 p-4 text-sm md:grid-cols-[1.2fr_1.2fr_0.8fr_auto] md:items-center" key={grant.id}>
                  <div>
                    <p className="text-slate-200">{account?.display_name ?? "账号已停用或不在当前列表"}</p>
                    <p className="mt-1 text-xs text-slate-500">{account?.platform.name ?? grant.account_id}</p>
                  </div>
                  <div>
                    <p className="text-slate-200">{member?.display_name ?? "成员已停用"}</p>
                    <p className="mt-1 text-xs text-slate-500">{member?.email ?? grant.user_id}</p>
                  </div>
                  <Badge tone={grant.permission === "editor" ? "success" : "info"}>
                    {grant.permission === "editor" ? "editor · 可编辑" : "viewer · 只读"}
                  </Badge>
                  <button className={`${secondaryButtonClass} h-8 px-2 text-rose-300`} disabled={pending} onClick={() => void revokeGrant(grant)} type="button">
                    <Trash2 size={13} />
                    撤销
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
