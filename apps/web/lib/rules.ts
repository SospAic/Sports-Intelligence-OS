import type {
  EditorialRuleSetDetail,
  EditorialRuleSetPage,
  EditorialRuleTree,
  EditorialRuleVersion,
} from "@sio/shared-types";
import { cookies } from "next/headers";

const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

async function getRuleResource<T>(
  path: string,
  workspaceId: string,
): Promise<T | null> {
  const cookieStore = await cookies();
  try {
    const response = await fetch(`${apiInternalUrl}/api/v1${path}`, {
      headers: {
        cookie: cookieStore.toString(),
        "X-Workspace-Id": workspaceId,
      },
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export function getRuleSets(workspaceId: string) {
  return getRuleResource<EditorialRuleSetPage>(
    "/rules?page=1&page_size=100",
    workspaceId,
  );
}

export function getRuleSetDetail(workspaceId: string, ruleSetId: string) {
  return getRuleResource<EditorialRuleSetDetail>(
    `/rules/${ruleSetId}`,
    workspaceId,
  );
}

export function getRuleVersion(
  workspaceId: string,
  ruleSetId: string,
  versionId: string,
) {
  return getRuleResource<EditorialRuleVersion>(
    `/rules/${ruleSetId}/versions/${versionId}`,
    workspaceId,
  );
}

export function getRuleTree(
  workspaceId: string,
  ruleSetId: string,
  versionId: string,
) {
  return getRuleResource<EditorialRuleTree>(
    `/rules/${ruleSetId}/versions/${versionId}/tree`,
    workspaceId,
  );
}
