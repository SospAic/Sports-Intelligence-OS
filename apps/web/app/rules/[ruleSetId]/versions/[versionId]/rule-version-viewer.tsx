"use client";

import type {
  EditorialRuleSectionNode,
  EditorialRuleTree,
  EditorialRuleVersion,
} from "@sio/shared-types";
import { useMemo, useState } from "react";

function sectionCards(sections: EditorialRuleSectionNode[]) {
  return sections.map((section) => (
    <details className="border-b border-slate-800 py-3" key={section.id}>
      <summary className="cursor-pointer text-sm font-medium text-slate-200">
        {section.title}{" "}
        <span className="text-slate-600">({section.rules.length})</span>
      </summary>
      <div className="mt-3 space-y-3 pl-3">
        {section.rules.map((rule) => (
          <article
            className="rounded-lg border border-slate-800 bg-slate-900/70 p-4"
            key={rule.id}
          >
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="text-cyan-300">{rule.key}</span>
              <span className="text-slate-500">{rule.rule_type}</span>
              {rule.source_reference && (
                <span className="text-slate-500">{rule.source_reference}</span>
              )}
            </div>
            <h3 className="mt-2 font-medium text-white">{rule.title}</h3>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-400">
              {rule.instruction}
            </p>
          </article>
        ))}
        {sectionCards(section.children)}
      </div>
    </details>
  ));
}

export function RuleVersionViewer({
  tree,
  version,
}: {
  tree: EditorialRuleTree;
  version: EditorialRuleVersion;
  ruleSetId?: string;
  versionId?: string;
  workspaceId?: string;
}) {
  const [view, setView] = useState<"structured" | "source" | "json">("structured");
  const jsonView = useMemo(() => JSON.stringify(tree, null, 2), [tree]);

  return (
    <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70">
      <div className="flex gap-2 border-b border-slate-800 p-4">
        {(["structured", "source", "json"] as const).map((item) => (
          <button
            className={`rounded-lg px-3 py-2 text-sm ${
              view === item ? "bg-cyan-300 text-slate-950" : "text-slate-300"
            }`}
            key={item}
            onClick={() => setView(item)}
            type="button"
          >
            {item === "structured" ? "结构化" : item === "source" ? "原文" : "JSON"}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-600">
          共 {tree.total_rules} 条规则
        </span>
      </div>
      <div className="max-h-[70vh] overflow-auto p-5">
        {view === "structured" ? (
          sectionCards(tree.sections)
        ) : (
          <pre className="whitespace-pre-wrap text-xs leading-5 text-slate-300">
            {view === "source" ? version.source_text : jsonView}
          </pre>
        )}
      </div>
    </section>
  );
}
