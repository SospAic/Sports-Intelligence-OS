import type { CsrfResponse, ProblemDetails } from "@sio/shared-types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

async function parseError(response: Response): Promise<ApiError> {
  const body = (await response
    .json()
    .catch(() => null)) as ProblemDetails | null;
  return new ApiError(
    body?.detail ?? `请求失败（HTTP ${response.status}）`,
    response.status,
    body?.code ?? "request_failed",
  );
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit & { workspaceId?: string; csrf?: boolean } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.workspaceId) headers.set("X-Workspace-Id", options.workspaceId);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (options.csrf) {
    const response = await fetch("/api/v1/auth/csrf", {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) throw await parseError(response);
    const csrf = (await response.json()) as CsrfResponse;
    headers.set("X-CSRF-Token", csrf.csrf_token);
  }
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function downloadApiFile(
  path: string,
  workspaceId: string,
  filename: string,
): Promise<void> {
  const response = await fetch(`/api/v1${path}`, {
    credentials: "include",
    cache: "no-store",
    headers: { "X-Workspace-Id": workspaceId },
  });
  if (!response.ok) throw await parseError(response);
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
