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

let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;

async function getCsrfToken(force = false): Promise<string> {
  if (!force && csrfToken) return csrfToken;
  if (!csrfRequest) {
    csrfRequest = fetch("/api/v1/auth/csrf", {
      credentials: "include",
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw await parseError(response);
        const csrf = (await response.json()) as CsrfResponse;
        csrfToken = csrf.csrf_token;
        return csrf.csrf_token;
      })
      .finally(() => {
        csrfRequest = null;
      });
  }
  return csrfRequest;
}

function isCsrfFailure(response: Response, body: ApiError): boolean {
  return response.status === 403 && body.code === "csrf_validation_failed";
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
    headers.set("X-CSRF-Token", await getCsrfToken());
  }
  const send = () =>
    fetch(`/api/v1${path}`, {
      ...options,
      headers: new Headers(headers),
      credentials: "include",
      cache: "no-store",
    });
  let response = await send();
  if (!response.ok && options.csrf) {
    const error = await parseError(response);
    if (isCsrfFailure(response, error)) {
      headers.set("X-CSRF-Token", await getCsrfToken(true));
      response = await send();
    } else {
      throw error;
    }
  }
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
