import type {
  EditorialRule,
  EditorialRuleSectionNode,
} from "@sio/shared-types";

export function flattenRuleSections(
  sections: EditorialRuleSectionNode[],
  depth = 0,
): Array<{ section: EditorialRuleSectionNode; depth: number }> {
  return sections.flatMap((section) => [
    { section, depth },
    ...flattenRuleSections(section.children, depth + 1),
  ]);
}

export function splitRuleValues(value: string): string[] {
  return [
    ...new Set(
      value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}

export function filterEditorialRules(
  rules: EditorialRule[],
  filters: { query: string; type: string; mandatoryOnly: boolean; tag: string },
): EditorialRule[] {
  const needle = filters.query.toLowerCase();
  const tagNeedle = filters.tag.toLowerCase();
  return rules.filter((rule) => {
    const text = `${rule.key} ${rule.title} ${rule.instruction}`.toLowerCase();
    return (
      (!needle || text.includes(needle)) &&
      (!filters.type || rule.rule_type === filters.type) &&
      (!filters.mandatoryOnly || rule.is_mandatory) &&
      (!tagNeedle ||
        rule.tags.some((item) => item.toLowerCase().includes(tagNeedle)))
    );
  });
}
