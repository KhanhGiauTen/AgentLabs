// The ordinary runtime plugin keeps its authored tools manifest. Only the public
// Control UI declaration is generated, with immutable, content-addressed assets.
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname, join, basename } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const { outputFiles } = await build({
  absWorkingDir: root,
  entryPoints: ["control-ui.ts"],
  outdir: "dist/control-ui/build",
  entryNames: "index",
  bundle: true,
  write: false,
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: true,
  legalComments: "none",
});
const hash = createHash("sha256");
const files = outputFiles.toSorted((a, b) => basename(a.path).localeCompare(basename(b.path)));
for (const file of files) hash.update(basename(file.path)).update(file.contents);
const relative = `dist/control-ui/${hash.digest("hex").slice(0, 24)}`;
await mkdir(join(root, relative), { recursive: true });
for (const file of files) await writeFile(join(root, relative, basename(file.path)), file.contents);
const pointer = join(root, "dist/openclaw.plugin.json");
const staged = `${pointer}.${process.pid}.tmp`;
await writeFile(staged, JSON.stringify({
  controlUi: { entry: `${relative}/index.js`, styles: [`${relative}/index.css`] },
}, null, 2) + "\n");
await rename(staged, pointer);
console.log("Built native AgentLabs chat UI (public Control UI contract).");
