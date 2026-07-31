import { defineConfig } from "vitest/config";
import path from "node:path";

// Ensure React loads its development build during tests so that
// `React.act` (required by @testing-library/react) is available. The web
// container otherwise inherits NODE_ENV=production from docker-compose, which
// loads the production React build and breaks component tests.
if (process.env.NODE_ENV === "production") {
  (process.env as { [key: string]: string | undefined }).NODE_ENV = "test";
}

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
      "@sio/ui": path.resolve(__dirname, "../../packages/ui/src/index.ts"),
      "@sio/shared-types": path.resolve(
        __dirname,
        "../../packages/shared-types/src/index.ts",
      ),
    },
  },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e/**"],
    setupFiles: ["./test/setup.ts"],
  },
});
