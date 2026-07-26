import {
  getContentEntries,
  getDomainSummaries,
  type ContentEntry,
  type Phase,
} from "./content-index";

// Derived views for the home page.
//
// The home page is a "work resumption point" rather than a domain catalog: the
// primary question it answers is "what did I add most recently, and where do I
// pick up?". That makes the report the unit of interest, with domains reduced to
// a secondary orientation aid (the full domain list already lives in the sidebar
// tree). Both views are projections over the single cached `getContentEntries()`
// scan, so nothing here re-reads the research tree.

const DEFAULT_REPORT_LIMIT = 15;
const DEFAULT_DOMAIN_LIMIT = 5;

export type RecentReport = {
  href: string;
  title: string;
  domain: string;
  phase?: Phase;
  runDate?: string;
  cluster?: string;
};

export type ActiveDomain = {
  domain: string;
  displayName: string;
  href: string;
  latestRunDate?: string;
  reportCount: number;
  phaseCounts: Record<Phase, number>;
};

export type HomeData = {
  recentReports: RecentReport[];
  activeDomains: ActiveDomain[];
  totalReportCount: number;
  totalDomainCount: number;
};

// Order reports newest-first, fully deterministically.
//
// `runDate` is best-effort: `parseRunContext` leaves it undefined whenever a run
// directory doesn't match `YYYYMMDD`. Those entries are pushed to the end rather
// than coerced to "" — an empty string would sort them as the *oldest* content
// and bury real reports beneath undated ones. Ties fall through to domain and
// then href so the order never shifts between ISR regenerations (entries arrive
// href-sorted, so a 0 comparison preserves that stable input order).
function compareByRecency(a: ContentEntry, b: ContentEntry): number {
  if (a.runDate !== b.runDate) {
    if (!a.runDate) return 1;
    if (!b.runDate) return -1;
    return b.runDate.localeCompare(a.runDate);
  }
  if (a.domain !== b.domain) return a.domain.localeCompare(b.domain);
  return a.href.localeCompare(b.href);
}

function toRecentReport(entry: ContentEntry): RecentReport {
  return {
    href: entry.href,
    title: entry.title,
    domain: entry.domain,
    phase: entry.phase,
    runDate: entry.runDate,
    cluster: entry.cluster,
  };
}

// The most recently produced reports across every domain.
export function getRecentReports(limit: number = DEFAULT_REPORT_LIMIT): RecentReport[] {
  return [...getContentEntries()]
    .sort(compareByRecency)
    .slice(0, limit)
    .map(toRecentReport);
}

// The domains with the most recent activity. `getDomainSummaries()` already
// sorts by latest run date (then display name), so this narrows that list to the
// fields the compact home chips actually render.
export function getActiveDomains(limit: number = DEFAULT_DOMAIN_LIMIT): ActiveDomain[] {
  return getDomainSummaries()
    .slice(0, limit)
    .map((summary) => ({
      domain: summary.domain,
      displayName: summary.displayName,
      href: summary.href,
      latestRunDate: summary.latestRunDate,
      reportCount: summary.reportCount,
      phaseCounts: summary.phaseCounts,
    }));
}

// Single entry point for the home page so the page component makes one call and
// the underlying scan is shared (see `getContentEntries`'s cache wrapper).
export function getHomeData(): HomeData {
  const summaries = getDomainSummaries();

  return {
    recentReports: getRecentReports(),
    activeDomains: getActiveDomains(),
    totalReportCount: getContentEntries().length,
    totalDomainCount: summaries.length,
  };
}
