"use client";

import type { CsrfResponse } from "@sio/shared-types";
import { Button } from "@sio/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function LogoutButton() {
  const router = useRouter();
  const [isPending, setIsPending] = useState(false);

  async function logout() {
    setIsPending(true);
    try {
      const csrfResponse = await fetch("/api/v1/auth/csrf", {
        credentials: "include",
        cache: "no-store",
      });
      if (!csrfResponse.ok) {
        throw new Error("Unable to obtain CSRF token");
      }
      const { csrf_token: csrfToken } =
        (await csrfResponse.json()) as CsrfResponse;
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": csrfToken },
      });
    } finally {
      router.replace("/login");
      router.refresh();
      setIsPending(false);
    }
  }

  return (
    <Button disabled={isPending} onClick={logout} variant="secondary">
      {isPending ? "退出中…" : "退出登录"}
    </Button>
  );
}
