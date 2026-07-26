import type { HomeData } from "@/lib/home-feed";
import { HomeSearch } from "./home-search";
import { RecentReports } from "./recent-reports";
import { ActiveDomains } from "./active-domains";

type HomeViewProps = {
  data: HomeData;
};

// Root landing view, framed as a work resumption point rather than a catalog.
// Ordered by what a returning reader actually needs: pick up where the content
// last changed (recent reports), find something specific (search), or check
// which domains are in flight (active domains).
export function HomeView({ data }: HomeViewProps) {
  const { recentReports, activeDomains, totalReportCount, totalDomainCount } =
    data;

  return (
    <div>
      {/* Title block, consistent with DirectoryIndex */}
      <div className="mb-8 brutal-border-strong brutal-shadow bg-[var(--surface-elevated)]">
        <div className="flex items-center justify-between brutal-border-b border-[var(--border-primary)] bg-[var(--text-primary)] px-4 py-2">
          <span className="brutal-label text-[var(--text-inverse)]">
            [INDEX] / ROOT
          </span>
          <span className="brutal-label tabular-nums text-[var(--text-inverse)]">
            DOMAINS: {String(totalDomainCount).padStart(2, "0")}
          </span>
        </div>
        <div className="px-6 py-6">
          <h1 className="brutal-display text-4xl text-[var(--text-primary)] md:text-5xl">
            RESEARCH
          </h1>
          <div className="mt-3 flex flex-wrap gap-3 brutal-label text-[var(--text-tertiary)]">
            <span className="tabular-nums">
              DOMAINS: {String(totalDomainCount).padStart(2, "0")}
            </span>
            <span>|</span>
            <span className="tabular-nums">
              REPORTS: {String(totalReportCount).padStart(3, "0")}
            </span>
          </div>
        </div>
      </div>

      <HomeSearch totalCount={totalReportCount} />
      <RecentReports reports={recentReports} />
      <ActiveDomains domains={activeDomains} />
    </div>
  );
}
