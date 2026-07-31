"use client";

import type { AuthResponse, ProblemDetails } from "@sio/shared-types";
import { Button } from "@sio/ui";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

const loginSchema = z.object({
  email: z.email("请输入有效邮箱"),
  password: z.string().min(1, "请输入密码"),
});

type LoginValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const router = useRouter();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginValues) {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });

    if (!response.ok) {
      const problem = (await response
        .json()
        .catch(() => null)) as ProblemDetails | null;
      setError("root", { message: problem?.detail ?? "登录失败，请稍后重试" });
      return;
    }

    (await response.json()) as AuthResponse;
    router.replace("/dashboard");
    router.refresh();
  }

  return (
    <form className="space-y-5" onSubmit={handleSubmit(onSubmit)} noValidate>
      <label className="block text-sm text-slate-300">
        邮箱
        <input
          className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-white outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
          autoComplete="email"
          type="email"
          {...register("email")}
        />
        {errors.email ? (
          <span className="mt-1 block text-xs text-rose-300">
            {errors.email.message}
          </span>
        ) : null}
      </label>
      <label className="block text-sm text-slate-300">
        密码
        <input
          className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-white outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
          autoComplete="current-password"
          type="password"
          {...register("password")}
        />
        {errors.password ? (
          <span className="mt-1 block text-xs text-rose-300">
            {errors.password.message}
          </span>
        ) : null}
      </label>
      {errors.root ? (
        <p
          className="rounded-lg border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-sm text-rose-200"
          role="alert"
        >
          {errors.root.message}
        </p>
      ) : null}
      <Button className="w-full" disabled={isSubmitting} type="submit">
        {isSubmitting ? "正在登录…" : "登录"}
      </Button>
    </form>
  );
}
