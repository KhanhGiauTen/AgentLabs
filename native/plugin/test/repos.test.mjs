import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Repositories, permitted } from "../repos.mjs";

test("source allowlist excludes credentials, datasets and traversal", () => {
  for (const p of [
    ".env",
    ".env.example",
    "../outside.py",
    "data/private.json",
    ".git/config",
    "keys/api-token.json",
    "credentials.yaml",
    "node_modules/lib/index.js",
    "checkpoints/model.txt",
    "secrets/notes.txt",
    ".env/safe.py",
  ])
    assert.equal(permitted(p), false, p);
  for (const p of [
    "src/train.py",
    "paper/main.tex",
    "src/tokenizer.py",
    "README.md",
    "pyproject.toml",
  ])
    assert.equal(permitted(p), true, p);
});
test("bounded read/search provide source hash and never write project files", async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), "agentlabs-repo-test-"));
  try {
    const root = path.join(temp, "repo");
    await fs.mkdir(root);
    await fs.mkdir(path.join(root, "src"));
    await fs.mkdir(path.join(root, "data"));
    await fs.writeFile(
      path.join(root, "src", "train.py"),
      "seed = 42\naccuracy = measured_value\n",
    );
    await fs.writeFile(path.join(root, ".env"), "API_KEY=synthetic");
    await fs.writeFile(path.join(root, "data", "private.json"), "private");
    const config = path.join(temp, "repos.json");
    await fs.writeFile(
      config,
      JSON.stringify({ pilot: await fs.realpath(root) }),
    );
    const repos = new Repositories(config);
    assert.deepEqual((await repos.files("pilot", () => {})).files, [
      "src/train.py",
    ]);
    const source = await repos.read("pilot", "src/train.py", 2, 1);
    assert.equal(source.start_line, 2);
    assert.match(source.sha256, /^[a-f0-9]{64}$/);
    assert.equal(source.content, "accuracy = measured_value");
    const result = await repos.search("pilot", "seed", () => {});
    assert.equal(result.matches[0].line, 1);
    await assert.rejects(
      () => repos.read("pilot", "../outside.py"),
      /not an allowed/,
    );
    await assert.rejects(() => repos.read("pilot", ".env"), /not an allowed/);
    await assert.rejects(() => repos.read("unknown", "src/train.py"), /not on/);
    await assert.rejects(
      () =>
        repos.read("pilot", "src/train.py", 1, 120, () => {
          throw new Error("revoked");
        }),
      /revoked/,
    );
    assert.equal(
      await fs.readFile(path.join(root, "src", "train.py"), "utf8"),
      "seed = 42\naccuracy = measured_value\n",
    );
  } finally {
    await fs.rm(temp, { recursive: true, force: true });
  }
});
test("resolved symlink cannot escape the allowlisted project", async (t) => {
  const temp = await fs.mkdtemp(
    path.join(os.tmpdir(), "agentlabs-repo-link-test-"),
  );
  try {
    const root = path.join(temp, "repo");
    await fs.mkdir(root);
    await fs.writeFile(path.join(temp, "outside.py"), "private content");
    try {
      await fs.symlink(
        path.join(temp, "outside.py"),
        path.join(root, "inside.py"),
      );
    } catch (error) {
      if (error.code === "EPERM") {
        t.skip(
          "Windows file symlink privilege absent; Linux CI exercises this case",
        );
        return;
      }
      throw error;
    }
    const config = path.join(temp, "repos.json");
    await fs.writeFile(
      config,
      JSON.stringify({ pilot: await fs.realpath(root) }),
    );
    await assert.rejects(
      () => new Repositories(config).read("pilot", "inside.py"),
      /escaped/,
    );
  } finally {
    await fs.rm(temp, { recursive: true, force: true });
  }
});
