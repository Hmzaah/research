import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { RecentReport } from "@/lib/home-feed";
import { PhaseBadge } from "./phase-badge";
import { formatRunDate } from "./format";

type RecentReportsProps = {
  reports: RecentReport[];
};

// The home page's primary content: the most recently produced reports, newest
// first, each linking straight to the document. Unlike the domain grid this
// replaces, a click here lands on actual content rather than another index.
export function RecentReports({ reports }: RecentReportsProps) {
  return (
    <section className="mb-10" data-testid="recent-reports">
      <h2 className="brutal-label mb-3 text-[var(--text-tertiary)]">
        {"// RECENT REPORTS"}
      </h2>

      {reports.length === 0 ? (
        <div className="brutal-border bg-[var(--surface-secondary)] p-8">
          <p className="brutal-label text-[var(--text-tertiary)]">
            &gt; NO REPORTS YET
          </p>
        </div>
      ) : (
        <ul className="brutal-border">
          {reports.map((report, idx) => (
            <li
              key={report.href}
              className={
                idx > 0 ? "brutal-border-t border-[var(--border-primary)]" : ""
              }
            >
              <Link
                href={report.href}
                className="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-[var(--accent-bg)] hover:text-[var(--accent-text)] sm:items-center sm:gap-4 sm:px-5"
              >
                <span className="brutal-label mt-0.5 w-8 shrink-0 tabular-nums text-[var(--text-tertiary)] group-hover:text-[var(--accent-text)] sm:mt-0 sm:w-10">
                  {String(idx + 1).padStart(3, "0")}
                </span>

                {/* Stacks on mobile (title over metadata) so long report titles
                    never force the row into a horizontal scroll. */}
                <span className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-center sm:gap-4">
                  <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-primary)] group-hover:text-[var(--accent-text)]">
                    {report.title}
                  </span>
                  <span className="flex shrink-0 items-center gap-2 brutal-label text-[var(--text-tertiary)] group-hover:text-[var(--accent-text)]">
                    <span className="truncate">{report.domain}</span>
                    {report.phase && <PhaseBadge phase={report.phase} />}
                    <span className="tabular-nums">
                      {formatRunDate(report.runDate)}
                    </span>
                  </span>
                </span>

                <ArrowUpRight
                  className="mt-0.5 h-4 w-4 shrink-0 text-[var(--text-primary)] transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-[var(--accent-text)] sm:mt-0"
                  strokeWidth={2.5}
                  aria-hidden
                />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
