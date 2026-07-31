import type { ProblemDetails } from "@sio/shared-types";
import { cookies } from "next/headers";

const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function serverApi<T>(
  path: string,
  workspaceId?: string,
): Promise<{ data: T | null; error: string | null }> {
  const cookieStore = await cookies();
  const headers: Record<string, string> = { cookie: cookieStore.toString() };
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  try {
    const response = await fetch(`${apiInternalUrl}/api/v1${path}`, {
      headers,
      cache: "no-store",
    });
    if (!response.ok) {
      const problem = (await response
        .json()
        .catch(() => null)) as ProblemDetails | null;
      return {
        data: null,
        error: problem?.detail ?? `API 请求失败（HTTP ${response.status}）`,
      };
    }
    return { data: (await response.json()) as T, error: null };
  } catch {
    return { data: null, error: "无法连接 API 服务，请检查服务状态后重试。" };
  }
}
