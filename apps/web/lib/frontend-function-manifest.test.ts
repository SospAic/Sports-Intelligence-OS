import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { FRONTEND_FUNCTION_MANIFEST } from "./frontend-function-manifest";

function pageFiles(root: string): string[] {
  const result: string[] = [];
  for (const entry of readdirSync(root)) {
    const full = join(root, entry);
    if (statSync(full).isDirectory()) result.push(...pageFiles(full));
    else if (entry === "page.tsx") result.push(full);
  }
  return result;
}

function routeFromPageFile(file: string): string {
  const relativePath = relative(join(process.cwd(), "app"), file)
    .split(sep)
    .join("/");
  const segments = relativePath.split("/").slice(0, -1);
  return segments.length ? `/${segments.join("/")}` : "/";
}

describe("frontend function inventory", () => {
  it("keeps every Next page route in the tested-function manifest", () => {
    const discovered = pageFiles(join(process.cwd(), "app"))
      .map(routeFromPageFile)
      .sort();
    const manifest = FRONTEND_FUNCTION_MANIFEST.map((item) => item.route).sort();

    expect(manifest).toEqual(discovered);
    expect(
      FRONTEND_FUNCTION_MANIFEST.every(
        (item) => item.criticalActions.length > 0 && item.tier,
      ),
    ).toBe(true);
  });
});
