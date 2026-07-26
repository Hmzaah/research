"use client";

import { Search } from "lucide-react";
import { useSearch } from "@/components/search/search-provider";

type HomeSearchProps = {
  totalCount: number;
};

// Prominent search affordance for the home page.
//
// Rendered as a button styled like an input rather than a real text field: the
// actual query UI is the existing CommandPalette, which already owns focus
// management, arrow-key navigation, Enter/Escape handling and aria-live result
// announcements. Duplicating an input here would fork that behavior and let the
// two entry points drift apart. The header's SearchTrigger stays as-is; this is
// the same action given the visual weight the landing page warrants.
export function HomeSearch({ totalCount }: HomeSearchProps) {
  const { openPalette } = useSearch();

  return (
    <button
      type="button"
      onClick={openPalette}
      data-testid="home-search"
      aria-label="リサーチを検索"
      aria-keyshortcuts="Meta+K Control+K"
      className="group mb-10 flex w-full items-center gap-3 brutal-border-strong brutal-shadow bg-[var(--surface-elevated)] px-4 py-4 text-left transition-colors hover:bg-[var(--accent-bg)] hover:text-[var(--accent-text)] cursor-pointer"
    >
      <Search
        className="h-5 w-5 shrink-0 text-[var(--text-primary)] group-hover:text-[var(--accent-text)]"
        strokeWidth={2.5}
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate text-sm text-[var(--text-secondary)] group-hover:text-[var(--accent-text)]">
        {totalCount} 件のレポートを検索…
      </span>
      <kbd className="brutal-label hidden shrink-0 brutal-border border-[var(--border-primary)] px-1.5 py-0.5 text-[var(--text-tertiary)] group-hover:border-[var(--accent-text)] group-hover:text-[var(--accent-text)] sm:inline-block">
        ⌘K
      </kbd>
    </button>
  );
}
