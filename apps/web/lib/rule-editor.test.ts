import type { EditorialRule } from "@sio/shared-types";
import { describe, expect, it } from "vitest";

import { filterEditorialRules, splitRuleValues } from "./rule-editor";

const baseRule = {
  id: "1",
  version_id: "v1",
  section_id: "s1",
  key: "kernel-01",
  title: "Answer Word Protection",
  rule_type: "narrative",
  instruction: "Protect the answer word until the reveal is earned.",
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
  tags: ["v7.9", "reveal"],
  source_reference: "lines:1-2",
  source_status: "full",
  sort_order: 1,
  created_at: "2026-07-26T00:00:00Z",
  updated_at: "2026-07-26T00:00:00Z",
} satisfies EditorialRule;

describe("rule editor filters", () => {
  it("combines search, type, mandatory and tag filters", () => {
    expect(
      filterEditorialRules([baseRule], {
        query: "answer word",
        type: "narrative",
        mandatoryOnly: true,
        tag: "reveal",
      }),
    ).toHaveLength(1);
    expect(
      filterEditorialRules([baseRule], {
        query: "answer word",
        type: "qa",
        mandatoryOnly: true,
        tag: "reveal",
      }),
    ).toHaveLength(0);
  });

  it("normalizes comma-separated batch properties", () => {
    expect(splitRuleValues("v7.9, reveal, v7.9, ")).toEqual(["v7.9", "reveal"]);
  });
});
