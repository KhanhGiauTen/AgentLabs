import * as fs from "node:fs/promises";
import path from "node:path";
import { sha } from "./domain.mjs";

const EXTENSIONS = new Set([
  ".py",
  ".md",
  ".txt",
  ".tex",
  ".bib",
  ".toml",
  ".yaml",
  ".yml",
  ".json",
  ".ipynb",
  ".js",
  ".jsx",
  ".ts",
  ".tsx",
  ".css",
  ".html",
  ".r",
  ".jl",
  ".cpp",
  ".h",
  ".rs",
  ".sh",
]);
const BLOCKED = new Set([
  ".git",
  ".venv",
  "venv",
  "node_modules",
  "__pycache__",
  "data",
  "datasets",
  "checkpoints",
  "wandb",
  "outputs",
  "logs",
  "dist",
  "build",
  ".ssh",
  ".aws",
  ".codex",
  "keys",
]);
export function permitted(relative) {
  const segments = relative.replaceAll("\\", "/").toLowerCase().split("/");
  if (segments.some((v) => !v || v === "." || v === ".." || BLOCKED.has(v)))
    return false;
  const name = segments.at(-1);
  if (
    segments.some(
      (segment) =>
        segment.startsWith(".env") ||
        /(?:^|[._-])(?:secrets?|credentials?|tokens?|api[_-]?keys?|access[_-]?tokens?|refresh[_-]?tokens?|private[_-]?keys?|auth[_-]?profiles?|id_(?:rsa|ed25519))(?:[._-]|$)/i.test(
          segment,
        ),
    )
  )
    return false;
  return EXTENSIONS.has(path.extname(name));
}

export class Repositories {
  constructor(configPath) {
    this.configPath = configPath;
  }
  async roots() {
    try {
      return JSON.parse(await fs.readFile(this.configPath, "utf8"));
    } catch (error) {
      if (error.code === "ENOENT") return {};
      throw error;
    }
  }
  async root(alias) {
    const roots = await this.roots();
    if (!Object.hasOwn(roots, alias))
      throw new Error(
        "Repository alias is not on the local read-only allowlist",
      );
    const configured = roots[alias];
    const canonical = await fs.realpath(configured);
    if (canonical.toLowerCase() !== path.resolve(configured).toLowerCase())
      throw new Error(
        "Repository root changed through a symlink/junction; re-register explicitly",
      );
    return canonical;
  }
  async files(alias, assertCurrent) {
    const root = await this.root(alias);
    const files = [];
    let inspected = 0;
    let truncated = false;
    const walk = async (directory) => {
      assertCurrent();
      const entries = await fs.readdir(directory, { withFileTypes: true });
      for (const entry of entries.sort((a, b) =>
        a.name.localeCompare(b.name),
      )) {
        if (++inspected > 3000 || files.length >= 500) {
          truncated = true;
          return;
        }
        if (entry.isSymbolicLink() || BLOCKED.has(entry.name.toLowerCase()))
          continue;
        const absolute = path.join(directory, entry.name);
        const relative = path.relative(root, absolute).replaceAll("\\", "/");
        if (entry.isDirectory()) await walk(absolute);
        else if (entry.isFile() && permitted(relative)) files.push(relative);
        if (truncated) return;
      }
    };
    await walk(root);
    assertCurrent();
    return { files, truncated };
  }
  async read(
    alias,
    relative,
    startLine = 1,
    lineCount = 120,
    assertCurrent = () => {},
  ) {
    if (
      path.isAbsolute(relative) ||
      relative.includes(":") ||
      !permitted(relative)
    )
      throw new Error("Path is not an allowed source file");
    const root = await this.root(alias);
    const absolute = await fs.realpath(path.join(root, relative));
    const resolved = path.relative(root, absolute);
    if (
      resolved.startsWith("..") ||
      path.isAbsolute(resolved) ||
      !permitted(resolved)
    )
      throw new Error("Resolved file escaped the source allowlist");
    const handle = await fs.open(absolute, "r");
    try {
      const stat = await handle.stat();
      if (!stat.isFile() || stat.size > 256000)
        throw new Error("Source file must be a regular file <=256 KB");
      // Bound the actual read even if another process grows the file after stat.
      const bytes = Buffer.alloc(256001);
      const { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
      if (bytesRead > 256000) throw new Error("Source file grew beyond limit");
      const content = bytes.subarray(0, bytesRead).toString("utf8");
      if (content.includes("\0"))
        throw new Error("Binary source is not supported");
      const lines = content.split(/\r?\n/);
      if (
        !Number.isInteger(startLine) ||
        startLine < 1 ||
        !Number.isInteger(lineCount) ||
        lineCount < 1 ||
        lineCount > 200
      )
        throw new Error("Invalid line range");
      const selected = lines
        .slice(startLine - 1, startLine - 1 + lineCount)
        .join("\n");
      assertCurrent();
      return {
        repo: alias,
        path: relative,
        sha256: sha(bytes.subarray(0, bytesRead)),
        start_line: startLine,
        total_lines: lines.length,
        content: selected.slice(0, 16000),
        truncated: selected.length > 16000,
      };
    } finally {
      await handle.close();
    }
  }
  async search(alias, query, assertCurrent) {
    if (!query || query.length > 150)
      throw new Error("Search literal must be 1–150 characters");
    const tree = await this.files(alias, assertCurrent);
    const matches = [];
    let scanned = 0;
    let skipped = 0;
    for (const file of tree.files) {
      if (scanned >= 150 || matches.length >= 25) break;
      scanned++;
      try {
        const source = await this.read(alias, file, 1, 200, assertCurrent);
        source.content.split("\n").forEach((line, i) => {
          if (
            matches.length < 25 &&
            line.toLowerCase().includes(query.toLowerCase())
          )
            matches.push({
              path: file,
              line: i + 1,
              text: line.slice(0, 240),
              sha256: source.sha256,
            });
        });
      } catch (error) {
        assertCurrent();
        skipped++;
      }
    }
    assertCurrent();
    return {
      matches,
      scanned_files: scanned,
      skipped_files: skipped,
      truncated:
        tree.truncated || scanned < tree.files.length || matches.length >= 25,
      scope:
        "literal search, first 200 lines / 16k characters of up to 150 source files",
    };
  }
}
