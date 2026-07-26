import type { Phase } from "@/lib/content-index";

type PhaseMeta = {
  label: string;
  title: string;
  bg: string;
  fg: string;
};

// Visual + semantic metadata per research phase. Colors are theme-aware tokens
// (defined in globals.css) so Gather / Retrieval / Clustering are
// distinguishable by hue as well as label — not by color alone, since the
// letter (G/R/C) and the title tooltip carry the meaning too.
const PHASE_META: Record<Phase, PhaseMeta> = {
  gather: {
    label: "G",
    title: "Gather — 収集フェーズ",
    bg: "var(--phase-gather-bg)",
    fg: "var(--phase-gather-fg)",
  },
  retrieval: {
    label: "R",
    title: "Retrieval — 詳細取得フェーズ",
    bg: "var(--phase-retrieval-bg)",
    fg: "var(--phase-retrieval-fg)",
  },
  clustering: {
    label: "C",
    title: "Clustering — クラスタリングフェーズ",
    bg: "var(--phase-clustering-bg)",
    fg: "var(--phase-clustering-fg)",
  },
};

type PhaseBadgeProps = {
  phase: Phase;
  // Omit for a bare phase marker (a single report belongs to exactly one phase,
  // so a count there would always read "1"). Provide it for per-domain tallies.
  count?: number;
};

// One phase chip. Colored when the phase is present; a neutral outlined chip
// when the count is explicitly zero (kept AA-legible rather than dimmed below
// contrast).
export function PhaseBadge({ phase, count }: PhaseBadgeProps) {
  const meta = PHASE_META[phase];

  if (count === 0) {
    return (
      <span
        title={`${meta.title}: 0 件`}
        className="brutal-border border-[var(--border-primary)]/30 px-1.5 py-0.5 tabular-nums text-[var(--text-tertiary)]"
      >
        {meta.label}:0
      </span>
    );
  }

  return (
    <span
      title={count === undefined ? meta.title : `${meta.title}: ${count} 件`}
      className="brutal-border px-1.5 py-0.5 tabular-nums"
      style={{
        backgroundColor: meta.bg,
        color: meta.fg,
        borderColor: meta.fg,
      }}
    >
      {count === undefined ? meta.label : `${meta.label}:${count}`}
    </span>
  );
}
