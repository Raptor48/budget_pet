/**
 * Tiny helpers shared by every Bot tab.
 *
 * Kept here (not in lib/) so they can be imported alongside the section
 * without polluting the global helper namespace.
 */

export function formatCents(cents: number, currency = "USD"): string {
  const sign = cents < 0 ? "-" : "";
  const value = Math.abs(cents) / 100;
  return currency === "USD"
    ? `${sign}$${value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`
    : `${sign}${value.toFixed(2)} ${currency}`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return value;
  }
}

export function todayMonday(): string {
  const d = new Date();
  const day = d.getDay(); // 0=Sun..6=Sat
  const diff = (day + 6) % 7; // back to Monday
  d.setDate(d.getDate() - diff);
  return d.toISOString().slice(0, 10);
}
