import { describe, expect, it } from "vitest";

import { accountDisplayName } from "./account-label";

describe("accountDisplayName", () => {
  it("turns a profile URL into a compact handle", () => {
    expect(
      accountDisplayName({
        display_name: "@https://www.tiktok.com/@creator",
      }),
    ).toBe("@creator");
  });

  it("does not expose a legacy placeholder as the account name", () => {
    expect(
      accountDisplayName({
        display_name: "的抖音",
        external_id: "sec_uid_123",
        platform_name: "抖音",
      }),
    ).toBe("抖音账号 · sec_uid_123");
  });
});
