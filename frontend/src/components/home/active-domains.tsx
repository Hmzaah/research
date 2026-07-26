import Link from "next/link";
import type { ActiveDomain } from "@/lib/home-feed";
import { PhaseBadge } from "./phase-badge";
import { formatRunDate } from "./format";

type ActiveDomainsProps = {
  domains: ActiveDomain[];
};

// Secondary orientation aid: the handful of domains with the most recent
// activity, with their phase progress (how far each has gotten through
// gather → retrieval → clustering). Deliberately compact — the complete domain
// list is always present in the sidebar tree, so repeating it here as a large
// card grid spent the most valuable screen space on navigation that was already
// available.
export function ActiveDomains({ domains }: ActiveDomainsProps) {
  if (domains.length === 0) return null;

  return (
    <section data-testid="active-domains">
      <h2 className="brutal-label mb-3 text-[var(--text-tertiary)]">
        {"// ACTIVE DOMAINS"}
      </h2>

      <div className="flex flex-wrap gap-3">
        {domains.map((domain) => (
          <Link
            key={domain.domain}
            href={domain.href}
            className="group flex items-center gap-3 brutal-border brutal-shadow-sm bg-[var(--surface-elevated)] px-3 py-2 transition-transform hover:-translate-x-0.5 hover:-translate-y-0.5 hover:brutal-shadow"
          >
            <span className="brutal-display text-sm text-[var(--text-primary)]">
              {domain.displayName}
            </span>
            <span className="flex items-center gap-1.5 brutal-label">
              <PhaseBadge phase="gather" count={domain.phaseCounts.gather} />
              <PhaseBadge
                phase="retrieval"
                count={domain.phaseCounts.retrieval}
              />
              <PhaseBadge
                phase="clustering"
                count={domain.phaseCounts.clustering}
              />
            </span>
            <span className="brutal-label tabular-nums text-[var(--text-tertiary)]">
              {formatRunDate(domain.latestRunDate)}
            </span>
          </Link>
        ))}
      </div>

      <p className="mt-3 brutal-label text-[var(--text-tertiary)]">
        &gt; 全ドメインはサイドバーから参照できます
      </p>
    </section>
  );
}
