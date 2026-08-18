import { afterEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "./browser-api";

function response(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("browser API CSRF handling", () => {
  it("retries a mutation once with a refreshed token when rotation raced", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ csrf_token: "csrf-1" }))
      .mockResolvedValueOnce(
        response({ code: "csrf_validation_failed", detail: "CSRF 校验失败" }, 403),
      )
      .mockResolvedValueOnce(response({ csrf_token: "csrf-2" }))
      .mockResolvedValueOnce(response({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiRequest("/downloads", {
        method: "POST",
        csrf: true,
        body: JSON.stringify({ url: "https://example.com/video" }),
      }),
    ).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(
      new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-CSRF-Token"),
    ).toBe("csrf-1");
    expect(
      new Headers(fetchMock.mock.calls[3]?.[1]?.headers).get("X-CSRF-Token"),
    ).toBe("csrf-2");
  });
});
