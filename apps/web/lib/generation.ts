import type {
  EditorialRuleSetPage,
  GenerationRun,
  GenerationRunPage,
  GenerationWorkflow,
  LLMProviderDescriptor,
  PromptCollectionDetail,
  PromptCollectionPage,
  PromptVersion,
} from "@sio/shared-types";
import { cookies } from "next/headers";

const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

async function getResource<T>(
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

export function getPrompts(workspaceId: string) {
  return getResource<PromptCollectionPage>(
    "/prompts?page=1&page_size=100",
    workspaceId,
  );
}

export function getPromptDetail(workspaceId: string, collectionId: string) {
  return getResource<PromptCollectionDetail>(
    `/prompts/${collectionId}`,
    workspaceId,
  );
}

export function getPromptVersion(
  workspaceId: string,
  collectionId: string,
  versionId: string,
) {
  return getResource<PromptVersion>(
    `/prompts/${collectionId}/versions/${versionId}`,
    workspaceId,
  );
}

export function getWorkflows(workspaceId: string) {
  return getResource<GenerationWorkflow[]>("/workflows", workspaceId);
}

export function getLLMProviders(workspaceId: string) {
  return getResource<LLMProviderDescriptor[]>("/llm/providers", workspaceId);
}

export function getGenerations(workspaceId: string) {
  return getResource<GenerationRunPage>(
    "/generations?page=1&page_size=50",
    workspaceId,
  );
}

export function getGeneration(workspaceId: string, runId: string) {
  return getResource<GenerationRun>(`/generations/${runId}`, workspaceId);
}

export function getGenerationRuleSets(workspaceId: string) {
  return getResource<EditorialRuleSetPage>(
    "/rules?page=1&page_size=100&status=active",
    workspaceId,
  );
}
