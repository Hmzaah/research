// Format a compact YYYYMMDD run date as YYYY.MM.DD for display. Returns the raw
// value if it doesn't match the expected shape, and an em dash when the run date
// is unknown (`parseRunContext` leaves it undefined for non-dated directories).
export function formatRunDate(runDate: string | undefined): string {
  if (!runDate) return "—";
  const match = runDate.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (!match) return runDate;
  return `${match[1]}.${match[2]}.${match[3]}`;
}
