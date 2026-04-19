/**
 * Shorten noisy institution / Plaid account product names for dense tables.
 * The raw string should still be shown in a `title` or tooltip — this is
 * display-only compaction, not a loss of stored data.
 */
export function abbreviateAccountDisplayName(raw: string | null | undefined): string {
  if (!raw?.trim()) return "";
  let s = raw.trim().replace(/\s+/g, " ");

  s = s
    .replace(/^total\s+/i, "")
    .replace(/\s+total\s+/gi, " ")
    .replace(/^everyday\s+/i, "")
    .replace(/\s+everyday\s+/gi, " ")
    .replace(/^primary\s+/i, "")
    .replace(/^preferred\s+/i, "")
    .replace(/^complete\s+access\s+/i, "")
    .replace(/^ultimate\s+rewards?\s+/i, "UR ")
    .replace(/^plaid\s+/i, "")
    .trim();

  s = s.replace(/\s+/g, " ");

  s = s.replace(/\bhigh\s+yield\s+/gi, "HY ").replace(/\s+/g, " ").trim();

  if (/^money\s+market$/i.test(s)) return "M.Mkt";
  s = s.replace(/\bmoney\s+market\b/gi, "M.Mkt");

  if (/^checking$/i.test(s)) return "Checking";
  if (/^savings$/i.test(s)) return "Savings";

  s = s
    .replace(/\bchecking\s+account\b/gi, "Chkg")
    .replace(/\bsavings\s+account\b/gi, "Svg")
    .replace(/\bcredit\s+card\b/gi, "Card")
    .replace(/\bchecking\b/gi, "Chkg")
    .replace(/\bsavings\b/gi, "Svg")
    .replace(/\s+/g, " ")
    .trim();

  const max = 22;
  if (s.length > max) {
    return `${s.slice(0, max - 1)}…`;
  }
  return s;
}
