import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules/**", ".next/**"],
  },
  resolve: {
    // `fileURLToPath`, not `new URL(...).pathname`. A `pathname` keeps the URL
    // encoding, so a checkout under a directory with a space in its name -
    // "git hub project" here - resolves `@/lib/x` to a path containing `%20`
    // and every runtime import through the alias fails to resolve. Type-only
    // imports are erased before resolution, which is why this stayed hidden
    // until the first component imported a module through `@`.
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
});
