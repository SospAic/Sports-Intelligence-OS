import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { LoginForm } from "./login-form";

export default async function LoginPage() {
  const currentUser = await getCurrentUser();
  if (currentUser) {
    redirect("/dashboard");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <section className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-950/75 p-8 shadow-2xl shadow-cyan-950/20 backdrop-blur">
        <div className="mb-8">
          <p className="mb-3 text-xs font-semibold tracking-[0.28em] text-cyan-300 uppercase">
            Sports Intelligence OS
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-white">
            登录工作台
          </h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">
            首个管理员需要通过受控 bootstrap
            命令创建，系统不会提供默认生产密码。
          </p>
        </div>
        <LoginForm />
      </section>
    </main>
  );
}
