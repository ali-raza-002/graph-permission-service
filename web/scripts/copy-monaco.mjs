// Serve Monaco from the app itself so the editor works offline and without a CDN.
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const source = join(dirname(require.resolve("monaco-editor/package.json")), "min", "vs");
const target = join(process.cwd(), "public", "monaco", "vs");

if (!existsSync(join(target, "loader.js"))) {
  mkdirSync(target, { recursive: true });
  cpSync(source, target, { recursive: true });
  console.log(`copied monaco to ${target}`);
}
