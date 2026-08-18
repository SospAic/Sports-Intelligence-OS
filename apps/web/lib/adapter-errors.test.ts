import { describe, expect, it } from "vitest";

import { adapterErrorCodeTone } from "./adapter-errors";

describe("adapterErrorCodeTone", () => {
  it("flags auth/permission errors as danger", () => {
    expect(adapterErrorCodeTone("authentication_error")).toBe("danger");
    expect(adapterErrorCodeTone("permission_denied")).toBe("danger");
    expect(adapterErrorCodeTone("adapter_configuration_error")).toBe("danger");
  });

  it("flags rate limit / transient errors as warning", () => {
    expect(adapterErrorCodeTone("rate_limited")).toBe("warning");
    expect(adapterErrorCodeTone("transient_provider_error")).toBe("warning");
  });

  it("treats not_found / contract / unknown codes and null as neutral", () => {
    expect(adapterErrorCodeTone("not_found")).toBe("neutral");
    expect(adapterErrorCodeTone("contract_mapping_error")).toBe("neutral");
    expect(adapterErrorCodeTone("capability_not_supported")).toBe("neutral");
    expect(adapterErrorCodeTone(null)).toBe("neutral");
    expect(adapterErrorCodeTone(undefined)).toBe("neutral");
  });
});
