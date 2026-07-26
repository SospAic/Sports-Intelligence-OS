import type {
  CurrentUserResponse,
  MonitoringAccountPage,
  ProblemDetails,
} from "@sio/shared-types";
import { cookies } from "next/headers";

const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

export async function getCurrentUser(): Promise<CurrentUserResponse | null> {
  const cookieStore = await cookies();

  try {
    const response = await fetch(`${apiInternalUrl}/api/v1/me`, {
      headers: { cookie: cookieStore.toString() },
      cache: "no-store",
    });

    if (response.status === 401) {
      return null;
    }

    if (!response.ok) {
      const problem = (await response
        .json()
        .catch(() => null)) as ProblemDetails | null;
      throw new Error(
        problem?.detail ?? `API request failed with ${response.status}`,
      );
    }

    return (await response.json()) as CurrentUserResponse;
  } catch (error) {
    if (
      error instanceof Error &&
      error.message.startsWith("API request failed")
    ) {
      throw error;
    }
    return null;
  }
}

export function getDisplayName(displayName: string, email: string): string {
  const normalizedName = displayName.trim();
  return normalizedName.length > 0 ? normalizedName : email;
}

export async function getMonitoringAccounts(
  workspaceId: string,
): Promise<MonitoringAccountPage | null> {
  const cookieStore = await cookies();
  try {
    const response = await fetch(
      `${apiInternalUrl}/api/v1/accounts?page=1&page_size=10&sort=last_synced_at&order=desc`,
      {
        headers: {
          cookie: cookieStore.toString(),
          "X-Workspace-Id": workspaceId,
        },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as MonitoringAccountPage;
  } catch {
    return null;
  }
}
