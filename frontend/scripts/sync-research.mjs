#!/usr/bin/env node
// Stage the display content into `frontend/research`.
//
// `docs-content.ts` and `content-index.ts` read `process.cwd()/research` at
// request time, and `next.config.ts` traces `./research/**` into the standalone
// bundle. That directory is a build artifact (gitignored), so a fresh checkout
// running `bun run dev` would otherwise hit ENOENT on every `/research` route.
//
// CI and Amplify stage the tree themselves (`cp -r research frontend/research`)
// and then layer the E2E fixtures on top via `setup-e2e-fixtures.mjs`. Because
// this script would re-copy over those fixtures, it SKIPS when the destination
// already exists — deleting a CI-generated fixture here would fail the E2E run
// in a way that is hard to trace back. Use `--force` to refresh deliberately.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = path.resolve(__dirname, "..", "..", "research");
const DEST = path.resolve(__dirname, "..", "research");

const force = process.argv.includes("--force");

if (!fs.existsSync(SOURCE)) {
  // Not an error: the tree may already be staged by CI with no sibling source.
  console.warn(`[sync-research] source not found, skipping: ${SOURCE}`);
  process.exit(0);
}

if (fs.existsSync(DEST) && !force) {
  console.log(
    "[sync-research] frontend/research already exists, skipping (use --force to refresh)",
  );
  process.exit(0);
}

fs.rmSync(DEST, { recursive: true, force: true });

// Shell out to `cp -r` rather than `fs.cpSync`, deliberately: `research/domains/**`
// is a symlink view onto `runs/`, and the production build (amplify.yml / CI)
// stages it with `cp -r`, which materializes those links as real directories.
// `fs.cpSync({ dereference: true })` does NOT recurse into a symlinked directory
// — it recreates it as a symlink pointing at the source tree, which then dangles
// inside the standalone bundle. Matching the production command keeps local and
// deployed layouts identical, which `content-index.ts` (isLatestAlias) assumes.
execFileSync("cp", ["-r", SOURCE, DEST], { stdio: "inherit" });

console.log(`[sync-research] copied ${SOURCE} -> ${DEST}`);
