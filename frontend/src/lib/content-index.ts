import fs from "node:fs";
import path from "node:path";
import { cache } from "react";
import { parse as parseYaml } from "yaml";
import { z } from "zod";

// Shared content-index basis for the Research Viewer.
//
// This module performs a SINGLE recursive scan of `research/**` and produces
// normalized, immutable data consumed by three features:
//   - cross-domain search (search-index.ts)
//   - the dashboard / landing (domain summaries)
//   - resource metadata cards (per-report structured metadata)
//
// Keeping the scan and normalization in one place avoids each feature
// re-reading and re-parsing Markdown frontmatter independently (DRY).

const RESEARCH_ROOT = path.join(process.cwd(), "research");
const DOMAINS_DIR = path.join(RESEARCH_ROOT, "domains");
const RUNS_DIR = path.join(RESEARCH_ROOT, "runs");

const IGNORED_NAMES = new Set(["node_modules", ".git", ".DS_Store"]);

// Known research phases. Anything else is left `undefined` so the UI can
// degrade gracefully rather than mislabel an unexpected directory.
export const PHASES = ["gather", "retrieval", "clustering"] as const;
export type Phase = (typeof PHASES)[number];

// Resource types as written in report headers (`- **Type**: ...`).
const RESOURCE_TYPES = [
  "Academic Paper",
  "Patent",
  "Web",
  "Business Case",
] as const;
type ResourceType = (typeof RESOURCE_TYPES)[number];

export type ContentEntry = {
  slug: string[];
  href: string;
  domain: string;
  title: string;
  type?: ResourceType;
  year?: string;
  venue?: string;
  authors?: string[];
  link?: string;
  phase?: Phase;
  runDate?: string;
  cluster?: string;
  headings: string[];
};

export type DomainSummary = {
  domain: string;
  displayName: string;
  description?: string;
  href: string;
  clusterCount: number;
  reportCount: number;
  latestRunDate?: string;
  phaseCounts: Record<Phase, number>;
};

// `domain.yaml` shape. Only the fields the viewer consumes are modeled; unknown
// keys are ignored so append-only content additions never break parsing.
const DomainYamlSchema = z.object({
  domain: z.string().optional(),
  display_name: z.string().optional(),
  description: z.string().optional(),
  clusters: z.array(z.unknown()).optional(),
});

function shouldInclude(name: string): boolean {
  return !IGNORED_NAMES.has(name) && !name.startsWith(".");
}

// `latest[_<cluster>]` run directories are symlink aliases of a dated run (per
// research directory rules). Skipping them by name keeps the dated directory as
// the canonical URL for every report, so search results and dashboard links
// point at a stable path rather than one that moves with each new run.
//
// The realpath dedup below is a second line of defence: the build-time copy
// preserves symlinks (`cp -a`), so an alias that slipped through would resolve
// to an already-seen file rather than a distinct duplicate.
function isLatestAlias(name: string): boolean {
  return name === "latest" || name.startsWith("latest_");
}

function isMarkdownFile(name: string): boolean {
  return name.endsWith(".md");
}

function toResourceType(value: string | undefined): ResourceType | undefined {
  return RESOURCE_TYPES.find((t) => t === value);
}

// Split a comma-separated author string into a trimmed, non-empty list.
function parseAuthors(value: string | undefined): string[] | undefined {
  if (!value) return undefined;
  const list = value
    .split(",")
    .map((a) => a.trim())
    .filter((a) => a.length > 0);
  return list.length > 0 ? list : undefined;
}

// Extract `- **Key**: value` metadata lines from the head of a report, stopping
// once a `## ` section begins after a Link was seen. Mirrors the historical
// behavior in docs-content.ts so both share one convention.
function extractHeaderMetadata(lines: string[]): Record<string, string> {
  const metadata: Record<string, string> = {};
  for (const line of lines) {
    const match = line.match(/^-\s+\*\*(.+?)\*\*:\s*(.+)$/);
    if (match) {
      metadata[match[1].toLowerCase()] = match[2].trim();
    }
    if (metadata["link"] && line.startsWith("## ")) break;
  }
  return metadata;
}

function extractTitle(lines: string[]): string {
  for (const line of lines) {
    const match = line.match(/^#\s+(.+)$/);
    if (match) return match[1].trim();
  }
  return "Untitled";
}

// Collect `##`+ heading text for search matching (the top-level `#` is title).
function extractHeadings(lines: string[]): string[] {
  const headings: string[] = [];
  for (const line of lines) {
    const match = line.match(/^#{2,6}\s+(.+)$/);
    if (match) headings.push(match[1].trim());
  }
  return headings;
}

// Parse run context from a slug relative to `research/`. Supports both layouts:
//   - current: `runs/<domain>/<phase>/<date>/<cluster>/...`
//              (clustering has no <cluster> segment: `.../<date>/...`)
//   - legacy:  `runs/<domain>/<phase>/<date>[_<cluster>]/...`
// Returns best-effort fields; unknown positions stay undefined.
function parseRunContext(slug: string[]): {
  domain: string;
  phase?: Phase;
  runDate?: string;
  cluster?: string;
} {
  // slug[0] is "runs" or "domains"; slug[1] is the domain.
  const domain = slug[1] ?? "unknown";
  const phase = PHASES.find((p) => p === slug[2]);

  let runDate: string | undefined;
  let cluster: string | undefined;

  const runSegment = slug[3];
  if (runSegment) {
    // Legacy combined form `<date>_<cluster>`.
    const combined = runSegment.match(/^(\d{8})_(.+)$/);
    if (combined) {
      runDate = combined[1];
      cluster = combined[2];
    } else if (/^\d{8}$/.test(runSegment)) {
      // Current form: `<date>` with the cluster (if any) as the next segment.
      runDate = runSegment;
      // clustering has no cluster dir; gather/retrieval do (slug[4]).
      const next = slug[4];
      // Only treat it as a cluster when there is a further path segment after
      // it (i.e. slug[4] is a directory, not the file itself).
      if (next && slug.length > 5) cluster = next;
    }
  }
  return { domain, phase, runDate, cluster };
}

// Recursively collect Markdown files under a directory, resolving symlinked
// dirs (e.g. `latest_*`) but recording each file once by its real path so
// symlink aliases don't produce duplicate entries.
function collectMarkdownFiles(
  dir: string,
  seenRealPaths: Set<string>,
): string[] {
  let dirents: fs.Dirent[];
  try {
    dirents = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }

  const files: string[] = [];
  for (const dirent of dirents) {
    if (!shouldInclude(dirent.name)) continue;
    if (isLatestAlias(dirent.name)) continue;
    const full = path.join(dir, dirent.name);

    // Resolve so symlinked directories are traversed and dedup is by real path.
    let stat: fs.Stats;
    try {
      stat = fs.statSync(full);
    } catch {
      continue;
    }

    if (stat.isDirectory()) {
      files.push(...collectMarkdownFiles(full, seenRealPaths));
    } else if (stat.isFile() && isMarkdownFile(dirent.name)) {
      const real = fs.realpathSync(full);
      if (seenRealPaths.has(real)) continue;
      seenRealPaths.add(real);
      files.push(full);
    }
  }
  return files;
}

function readDomainYaml(domain: string): z.infer<typeof DomainYamlSchema> | null {
  const yamlPath = path.join(DOMAINS_DIR, domain, "domain.yaml");
  if (!fs.existsSync(yamlPath)) return null;
  try {
    const raw = parseYaml(fs.readFileSync(yamlPath, "utf-8"));
    const parsed = DomainYamlSchema.safeParse(raw);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

function buildEntry(fullPath: string): ContentEntry | null {
  let content: string;
  try {
    content = fs.readFileSync(fullPath, "utf-8");
  } catch {
    return null;
  }

  const relative = path.relative(RESEARCH_ROOT, fullPath);
  const slugWithExt = relative.split(path.sep);
  const slug = [
    ...slugWithExt.slice(0, -1),
    slugWithExt[slugWithExt.length - 1].replace(/\.md$/, ""),
  ];

  const lines = content.split("\n");
  const metadata = extractHeaderMetadata(lines);
  const { domain, phase, runDate, cluster } = parseRunContext(slug);

  return {
    slug,
    href: `/research/${slug.join("/")}`,
    domain,
    title: extractTitle(lines),
    type: toResourceType(metadata["type"]),
    year: metadata["year"],
    venue: metadata["venue"],
    authors: parseAuthors(metadata["authors"]),
    link: metadata["link"],
    phase,
    runDate,
    cluster,
    headings: extractHeadings(lines),
  };
}

// Scan every Markdown report under `research/runs/**`, deduped by real path.
//
// Wrapped in React's `cache` so the full recursive scan (which reads every
// Markdown file in the tree) runs once per request rather than once per caller:
// the authenticated layout builds the search index while the home page builds
// both the recent-report feed and the domain summaries. The research tree is
// append-only and grows without bound, so collapsing those into one pass keeps
// render cost flat as content accumulates.
export const getContentEntries = cache((): ContentEntry[] => {
  const seen = new Set<string>();
  const files = collectMarkdownFiles(RUNS_DIR, seen);
  const entries: ContentEntry[] = [];
  for (const file of files) {
    const entry = buildEntry(file);
    if (entry) entries.push(entry);
  }
  return entries.sort((a, b) => a.href.localeCompare(b.href));
});

// Aggregate per-domain summaries for the dashboard, preferring `domain.yaml`
// metadata (display_name/description/clusters) when present.
export function getDomainSummaries(): DomainSummary[] {
  const entries = getContentEntries();

  const byDomain = new Map<string, ContentEntry[]>();
  for (const entry of entries) {
    const list = byDomain.get(entry.domain);
    if (list) list.push(entry);
    else byDomain.set(entry.domain, [entry]);
  }

  const domains = listDomains();
  const summaries: DomainSummary[] = [];

  for (const domain of domains) {
    const domainEntries = byDomain.get(domain) ?? [];
    const yaml = readDomainYaml(domain);

    const phaseCounts: Record<Phase, number> = {
      gather: 0,
      retrieval: 0,
      clustering: 0,
    };
    let latestRunDate: string | undefined;
    for (const entry of domainEntries) {
      if (entry.phase) phaseCounts[entry.phase] += 1;
      if (entry.runDate && (!latestRunDate || entry.runDate > latestRunDate)) {
        latestRunDate = entry.runDate;
      }
    }

    summaries.push({
      domain,
      displayName: yaml?.display_name ?? domain,
      description: yaml?.description,
      href: `/research/domains/${domain}`,
      clusterCount: yaml?.clusters?.length ?? 0,
      reportCount: domainEntries.length,
      latestRunDate,
      phaseCounts,
    });
  }

  // Most-recently-updated domains first so active work surfaces at the top of
  // the dashboard; fall back to name for stable ordering when dates tie.
  return summaries.sort((a, b) => {
    const dateA = a.latestRunDate ?? "";
    const dateB = b.latestRunDate ?? "";
    if (dateA !== dateB) return dateB.localeCompare(dateA);
    return a.displayName.localeCompare(b.displayName);
  });
}

// List domain directories from `runs/` and `domains/` (union), so domains
// without a `domain.yaml` still surface.
function listDomains(): string[] {
  const names = new Set<string>();
  for (const base of [RUNS_DIR, DOMAINS_DIR]) {
    try {
      for (const dirent of fs.readdirSync(base, { withFileTypes: true })) {
        if (dirent.isDirectory() && shouldInclude(dirent.name)) {
          names.add(dirent.name);
        }
      }
    } catch {
      // Missing base directory: skip.
    }
  }
  return [...names];
}
