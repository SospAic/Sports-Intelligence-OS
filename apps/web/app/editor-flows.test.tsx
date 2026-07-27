// @vitest-environment jsdom

import type {
  EditorialRule,
  EditorialRuleSetSummary,
  EditorialRuleTree,
  GenerationWorkflow,
  LLMProviderDescriptor,
  NotificationChannelRecord,
  PromptVersion,
} from "@sio/shared-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
}));
const apiRequestMock = vi.hoisted(() => vi.fn());
const notifyMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/app-shell", () => ({
  useWorkspace: () => ({ workspaceId: "workspace-1", role: "owner" }),
}));
vi.mock("@/components/toast", () => ({
  useToast: () => ({ notify: notifyMock }),
}));
vi.mock("@/lib/browser-api", () => ({
  apiRequest: apiRequestMock,
  downloadApiFile: vi.fn(),
}));

import { GenerationForm } from "./generate/generation-form";
import { LoginForm } from "./login/login-form";
import { NotificationChannelsClient } from "./notification-channels/notification-channels-client";
import { PromptEditor } from "./prompts/[id]/prompt-editor";
import { RuleEditor } from "./rules/[ruleSetId]/edit/rule-editor";
import { LLMSettingsPanel } from "./settings/llm-settings-panel";
import { RuntimeSettingsPanel } from "./settings/runtime-settings-panel";

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function withQueryClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}

beforeEach(() => {
  navigation.push.mockReset();
  navigation.replace.mockReset();
  navigation.refresh.mockReset();
  apiRequestMock.mockReset();
  notifyMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("登录与编辑器交互", () => {
  it("登录成功后只提交凭证并进入仪表盘", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({
        user: { id: "u1", email: "admin@example.com", display_name: "管理员" },
        csrf_token: "csrf",
        expires_at: "2026-07-27T00:00:00Z",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText("邮箱"), "admin@example.com");
    await user.type(screen.getByLabelText("密码"), "safe-password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith("/dashboard"),
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      email: "admin@example.com",
      password: "safe-password",
    });
  });

  it("规则编辑会携带 CSRF、工作区和结构化字段保存草稿", async () => {
    const rule: EditorialRule = {
      id: "rule-1",
      version_id: "version-1",
      section_id: "section-1",
      key: "answer-word",
      title: "Answer Word Protection",
      rule_type: "narrative",
      instruction: "Protect the answer word.",
      why: null,
      how: null,
      good_example: null,
      bad_example: null,
      qa_check: null,
      rewrite_instruction: null,
      priority: 100,
      severity: "critical",
      is_mandatory: true,
      enabled: true,
      sports: [],
      story_types: [],
      output_types: [],
      dependencies: [],
      conflicts: [],
      tags: ["v7.9"],
      source_reference: "lines:1-2",
      source_status: "full",
      sort_order: 1,
      created_at: "2026-07-26T00:00:00Z",
      updated_at: "2026-07-26T00:00:00Z",
    };
    const tree: EditorialRuleTree = {
      version: {
        id: "version-1",
        version: "7.9-test",
        source_hash: "hash",
        changelog: null,
        status: "draft",
        created_by: "u1",
        created_at: "2026-07-26T00:00:00Z",
        published_at: null,
      },
      sections: [
        {
          id: "section-1",
          version_id: "version-1",
          parent_id: null,
          title: "Core",
          slug: "core",
          description: null,
          sort_order: 1,
          rules: [rule],
          children: [],
        },
      ],
      total_rules: 1,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ csrf_token: "csrf-rule" }))
      .mockResolvedValueOnce(
        response({
          version_id: "version-1",
          created_draft: false,
          rule: { ...rule, instruction: "Updated instruction" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <RuleEditor workspaceId="workspace-1" ruleSetId="set-1" tree={tree} />,
    );

    const instruction = screen.getByLabelText("Instruction");
    await user.clear(instruction);
    await user.type(instruction, "Updated instruction");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));

    await screen.findByText("草稿已保存");
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toContain("/rules/set-1/versions/version-1/rules/rule-1");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf-rule");
    expect(JSON.parse(String(init.body)).instruction).toBe(
      "Updated instruction",
    );
  });

  it("Prompt 编辑器保存版本化正文和模型配置", async () => {
    const version: PromptVersion = {
      id: "prompt-version-1",
      collection_id: "prompt-1",
      version: "1.0.0",
      system_prompt: "Original system prompt",
      user_prompt_template: "Write {{title}}",
      variables_schema: { type: "object" },
      model_config: { temperature: 0.4 },
      changelog: null,
      status: "draft",
      created_by: "u1",
      created_at: "2026-07-26T00:00:00Z",
      published_at: null,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ csrf_token: "csrf-prompt" }))
      .mockResolvedValueOnce(
        response({ ...version, system_prompt: "Updated system prompt" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <PromptEditor
        workspaceId="workspace-1"
        collectionId="prompt-1"
        version={version}
      />,
    );

    const systemPrompt = screen.getByLabelText("System Prompt");
    await user.clear(systemPrompt);
    await user.type(systemPrompt, "Updated system prompt");
    await user.click(screen.getByRole("button", { name: "保存草稿" }));

    await screen.findByText("草稿已保存");
    const [, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).system_prompt).toBe(
      "Updated system prompt",
    );
    expect(new Headers(init.headers).get("X-Workspace-Id")).toBe("workspace-1");
  });
});

describe("生成和通知真实前端流程", () => {
  it("内容创作页面只暴露素材和规则并使用内置 Prompt 一键生成", async () => {
    const workflow: GenerationWorkflow = {
      id: "workflow-1",
      key: "sports-full-package",
      name: "Sports Short Video Full Package",
      description: null,
      input_types: ["news", "event", "content", "user_text"],
      steps: [
        {
          key: "research",
          name: "Research Input",
          sort_order: 1,
          required: true,
        },
      ],
      default_rule_set_version_id: "rules-79",
      default_prompt_version_id: "prompt-version-1",
      enabled: true,
      created_at: "2026-07-26T00:00:00Z",
      updated_at: "2026-07-26T00:00:00Z",
    };
    const provider: LLMProviderDescriptor = {
      key: "mock_llm",
      name: "Mock LLM（测试）",
      configured: true,
      is_mock: true,
      supports_streaming: false,
      detail: "Only deterministic test output",
      source: "builtin",
      default_model: "mock-sports-writer-v1",
      default_parameters: {
        temperature: 0.2,
        top_p: 1,
        max_tokens: 2048,
      },
    };
    const ruleSet: EditorialRuleSetSummary = {
      id: "rule-set-1",
      key: "elite-sports-narration-v7-9",
      name: "7.9 体育叙事规则",
      description: null,
      current_version_id: "rules-79",
      status: "active",
      tags: [],
      version_count: 1,
      draft_count: 0,
      created_at: "2026-07-26T00:00:00Z",
      updated_at: "2026-07-26T00:00:00Z",
    };
    apiRequestMock.mockImplementation(async (path: string) => {
      if (path.startsWith("/contents?")) {
        return { items: [], page: 1, page_size: 12, total: 0 };
      }
      if (path === "/generations") return { id: "generation-1" };
      throw new Error(`Unexpected API path: ${path}`);
    });
    const user = userEvent.setup();
    withQueryClient(
      <GenerationForm
        workspaceId="workspace-1"
        workflows={[workflow]}
        providers={[provider]}
        ruleSets={[ruleSet]}
      />,
    );

    await user.click(screen.getByRole("tab", { name: "自定义材料" }));
    await user.type(
      screen.getByPlaceholderText(/粘贴事件事实/),
      "User supplied sports facts without independent verification.",
    );
    expect(screen.queryByText("Prompt 版本")).not.toBeInTheDocument();
    expect(screen.queryByText("Temperature")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /立即生成内容包/ }));

    await waitFor(() =>
      expect(navigation.push).toHaveBeenCalledWith("/generations/generation-1"),
    );
    const call = apiRequestMock.mock.calls.find(
      ([path]) => path === "/generations",
    );
    expect(call).toBeDefined();
    const payload = JSON.parse(String(call?.[1]?.body));
    expect(payload.workflow_id).toBe("workflow-1");
    expect(payload.prompt_version_id).toBeNull();
    expect(payload.provider).toBe("mock_llm");
    expect(payload.model_config).toMatchObject({
      target_min_chars: 1200,
      target_max_chars: 1250,
      max_rewrites: 2,
    });
  });

  it("通知渠道测试先确认，再调用后端测试 API 并展示回执", async () => {
    const channel: NotificationChannelRecord = {
      id: "channel-1",
      provider_key: "mock_notification",
      name: "Mock Webhook（测试）",
      config_masked: {},
      enabled: true,
      last_tested_at: null,
      health_status: "unknown",
      created_at: "2026-07-26T00:00:00Z",
      updated_at: "2026-07-26T00:00:00Z",
    };
    apiRequestMock.mockImplementation(async (path: string) => {
      if (path === "/notification-providers")
        return [
          {
            key: "mock_notification",
            name: "Mock Notification（测试）",
            is_mock: true,
            config_fields: [],
          },
        ];
      if (path === "/notification-channels") return [channel];
      if (path.startsWith("/notification-deliveries"))
        return { items: [], page: 1, page_size: 50, total: 0 };
      if (path === "/notification-channels/channel-1/test")
        return { status: "delivered" };
      throw new Error(`Unexpected API path: ${path}`);
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    withQueryClient(<NotificationChannelsClient />);

    await screen.findByText("Mock Webhook（测试）");
    await user.click(screen.getByRole("button", { name: "测试" }));

    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        "/notification-channels/channel-1/test",
        expect.objectContaining({ method: "POST", csrf: true }),
      ),
    );
    expect(window.confirm).toHaveBeenCalledWith("发送 Mock 测试通知？");
    expect(notifyMock).toHaveBeenCalledWith("测试通知已投递", "success");
  });

  it("prevents password managers from autofilling notification credentials", async () => {
    apiRequestMock.mockImplementation(async (path: string) => {
      if (path === "/notification-providers")
        return [
          {
            key: "email",
            name: "Email",
            is_mock: false,
            config_fields: [
              {
                key: "username",
                label: "SMTP username",
                value_type: "string",
                required: false,
                secret: false,
                options: [],
              },
              {
                key: "password",
                label: "SMTP password",
                value_type: "password",
                required: false,
                secret: true,
                options: [],
              },
            ],
          },
        ];
      if (path === "/notification-channels") return [];
      if (path.startsWith("/notification-deliveries"))
        return { items: [], page: 1, page_size: 50, total: 0 };
      throw new Error(`Unexpected API path: ${path}`);
    });
    const user = userEvent.setup();
    withQueryClient(<NotificationChannelsClient />);

    await user.click(await screen.findByRole("button", { name: "添加渠道" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Provider" }),
      "email",
    );

    expect(screen.getByLabelText("SMTP username")).toHaveAttribute(
      "autocomplete",
      "off",
    );
    expect(screen.getByLabelText("SMTP password")).toHaveAttribute(
      "autocomplete",
      "new-password",
    );
    expect(screen.getByLabelText("SMTP password")).toHaveAttribute(
      "data-lpignore",
      "true",
    );
  });

  it("设置中心展示数据库细项并把工作区 LLM 参数加密提交到后端", async () => {
    const llmSetting = {
      id: null,
      provider_key: "openai_compatible",
      name: "OpenAI 兼容接口",
      source: "unconfigured" as const,
      base_url: "https://api.openai.com/v1",
      api_key_configured: false,
      config_masked: {},
      default_model: "gpt-4.1-mini",
      default_parameters: {
        temperature: 0.4,
        top_p: 1,
        max_tokens: 4096,
        timeout_seconds: 60,
        max_attempts: 3,
      },
      input_cost_per_million: null,
      output_cost_per_million: null,
      enabled: true,
      configured: false,
      last_tested_at: null,
      health_status: "unknown",
      updated_at: null,
      fields: [],
    };
    apiRequestMock.mockImplementation(
      async (path: string, options?: RequestInit) => {
        if (path === "/settings/runtime") {
          return {
            environment: "test",
            apply_mode: "environment_restart",
            warning: "重启后生效",
            sections: [
              {
                key: "database",
                title: "PostgreSQL / 数据库",
                description: "脱敏连接",
                fields: [
                  {
                    key: "database_pool_size",
                    label: "连接池基础连接数",
                    value: 10,
                    value_type: "number",
                    env_var: "SIO_DATABASE_POOL_SIZE",
                    description: "每进程连接数",
                    secret: false,
                    restart_required: true,
                    minimum: 1,
                    maximum: 100,
                  },
                ],
              },
            ],
          };
        }
        if (
          path === "/settings/llm/openai-compatible" &&
          options?.method === "PUT"
        ) {
          return { ...llmSetting, source: "database", configured: true };
        }
        if (path === "/settings/llm/openai-compatible") return llmSetting;
        if (path === "/llm/providers") return [];
        throw new Error(`Unexpected API path: ${path}`);
      },
    );

    const runtimeView = withQueryClient(<RuntimeSettingsPanel />);
    await screen.findByText("连接池基础连接数");
    expect(screen.getByDisplayValue("10")).toHaveAttribute("min", "1");
    runtimeView.unmount();

    const user = userEvent.setup();
    withQueryClient(<LLMSettingsPanel />);
    const keyInput = await screen.findByLabelText(/^API Key/);
    await user.type(keyInput, "sk-browser-secret");
    const modelInput = screen.getByLabelText("默认模型");
    await user.clear(modelInput);
    await user.type(modelInput, "sports-model-v2");
    await user.click(screen.getByRole("button", { name: "保存配置" }));

    await waitFor(() =>
      expect(apiRequestMock).toHaveBeenCalledWith(
        "/settings/llm/openai-compatible",
        expect.objectContaining({
          method: "PUT",
          csrf: true,
          workspaceId: "workspace-1",
        }),
      ),
    );
    const saveCall = apiRequestMock.mock.calls.find(
      ([path, options]) =>
        path === "/settings/llm/openai-compatible" && options?.method === "PUT",
    );
    const payload = JSON.parse(String(saveCall?.[1]?.body));
    expect(payload).toMatchObject({
      api_key: "sk-browser-secret",
      default_model: "sports-model-v2",
      temperature: 0.4,
      top_p: 1,
      max_tokens: 4096,
    });
  });
});
