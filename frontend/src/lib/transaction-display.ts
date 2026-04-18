/**
 * Display title normalization for transactions and recurring streams.
 *
 * Mirrors the backend rules in `web/transactions/display.py`. Used as a
 * client-side fallback when the backend has not yet populated `display_title`.
 *
 * Priority of sources (first non-empty wins):
 *   1. `merchant_name` (Plaid enriched, already pretty)
 *   2. `counterparties[]` — first entry with type='merchant', otherwise the
 *      entry with the highest `confidence_level`.
 *   3. Hostname extracted from `website`.
 *   4. Heuristically cleaned `name` / `description`.
 *   5. Fallback "Transaction".
 */

const MAX_LEN = 42;

const CONFIDENCE_RANK: Record<string, number> = {
  VERY_HIGH: 4,
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
  UNKNOWN: 0,
};

const PREFIXES: string[] = [
  "REAL\\s+TIME\\s+TRANSFER\\s+(?:RECD|RECEIVED)\\s+FROM",
  "REAL\\s+TIME\\s+TRANSFER\\s+(?:SENT\\s+TO|TO)",
  "PURCHASE\\s+AUTHORIZED\\s+ON\\s+\\d{1,2}/\\d{1,2}",
  "DEBIT\\s+CARD\\s+(?:PURCHASE|PAYMENT)",
  "CREDIT\\s+CARD\\s+PAYMENT",
  "POS\\s+(?:PURCHASE|DEBIT)",
  "ZELLE\\s+PAYMENT\\s+(?:TO|FROM)",
  "ZELLE\\s+(?:TO|FROM)",
  "ACH\\s+(?:DEBIT|CREDIT)\\s+(?:FROM|TO)",
  "ACH\\s+(?:DEBIT|CREDIT)",
  "ELECTRONIC\\s+(?:WITHDRAWAL|DEPOSIT)",
  "ONLINE\\s+(?:PMT|PAYMENT|TRANSFER)\\s+(?:TO|FROM)?",
  "BILL\\s+PAYMENT",
  "CHECKCARD\\s+\\d{1,4}",
  "CHECKCARD",
  "CHECK\\s+CARD\\s+PURCHASE",
  "WEB\\s+AUTHORIZED\\s+PMT",
  "RECURRING\\s+(?:PAYMENT|DEBIT)",
  "AUTO\\s+PAY",
  "WIRE\\s+TRANSFER\\s+(?:TO|FROM)?",
  "DIRECT\\s+DEPOSIT",
  "DEPOSIT\\s+FROM",
];
const PREFIX_RE = new RegExp(`^\\s*(?:${PREFIXES.join("|")})\\b[:\\s\\-]*`, "i");

const META_FRAGMENTS: string[] = [
  "\\bORIG\\s+(?:CO\\s+)?NAME[:#]\\s*\\S+",
  "\\bORIG\\s+ID[:#]\\s*\\S+",
  "\\bCO\\s+(?:ENTRY\\s+DESCR|ID)[:#]\\s*\\S+",
  "\\bCO\\s+ENTRY\\s+DESCR[:#]?\\s*\\S+",
  "\\b(?:CCD|PPD|WEB|TEL|CTX|IAT|ARC)\\s+ID[:#]?\\s*\\S+",
  "\\b(?:CCD|PPD|WEB|TEL|CTX|IAT|ARC)\\b",
  "\\bID[:#]\\s*\\S+",
  "\\bIID[:#]?\\s*\\S+",
  "\\bINFO[:#]?\\s*\\S+",
  "\\bREF\\s*#?\\s*\\S+",
  "\\bF[:#]\\d+",
  "\\b\\d{2}/\\d{2}(?:/\\d{2,4})?\\b",
  "\\b\\d{2}-\\d{2}-\\d{2,4}\\b",
  "#\\s*\\d+",
];
const META_RE = new RegExp(META_FRAGMENTS.join("|"), "gi");

const LONG_ID_RE = /\b(?=[A-Z0-9]{10,}\b)(?=[A-Z0-9]*\d)[A-Z0-9]+\b/g;
const TRAILING_NUM_RE = /\s+\d{1,4}\s*$/;
const MULTISPACE_RE = /\s+/g;
const LEADING_PUNCT_RE = /^[\s:\-#*]+/;
const TRAILING_PUNCT_RE = /[\s:\-#*]+$/;

const ACRONYMS = new Set([
  "IRS", "USPS", "ATM", "POS", "CD", "DD", "USA", "USD", "DMV", "NYC",
  "LLC", "INC", "CO", "AT&T", "AMEX", "PNC", "BMO", "TD", "FCU", "DBA",
  "NSF", "ACH", "EFT", "PIN", "ID", "TV", "AC", "DC", "SF", "LA",
  "EU", "UK", "VA", "MA", "PA", "NJ", "CA", "TX", "FL", "IL", "OH",
]);
const LOWERCASE_WORDS = new Set([
  "and", "of", "the", "for", "to", "in", "at", "by", "on", "or",
]);

interface CounterpartyLike {
  name?: string | null;
  type?: string | null;
  confidence_level?: string | null;
}

interface TitleSource {
  merchant_name?: string | null;
  counterparties?: CounterpartyLike[] | null;
  website?: string | null;
  name?: string | null;
  description?: string | null;
  display_title?: string | null;
}

function coerceStr(value: unknown): string {
  if (value == null) return "";
  return String(value).trim();
}

function looksPretty(value: string): boolean {
  if (!value) return false;
  if (/[a-z]/.test(value)) return true;
  return value.length <= 24 && !/\d/.test(value);
}

function fromCounterparties(parties: CounterpartyLike[] | null | undefined): string | null {
  if (!parties || parties.length === 0) return null;
  const merchants = parties.filter(
    (c) => (c.type ?? "").toLowerCase() === "merchant",
  );
  const pool = merchants.length > 0 ? merchants : parties;
  const sorted = [...pool].sort(
    (a, b) =>
      (CONFIDENCE_RANK[b.confidence_level ?? "UNKNOWN"] ?? 0) -
      (CONFIDENCE_RANK[a.confidence_level ?? "UNKNOWN"] ?? 0),
  );
  for (const c of sorted) {
    const name = coerceStr(c.name);
    if (name) return name;
  }
  return null;
}

function hostnameFromWebsite(website: string): string | null {
  if (!website) return null;
  let raw = website.trim().toLowerCase();
  raw = raw.replace(/^https?:\/\//, "");
  raw = raw.split("/", 1)[0];
  if (raw.startsWith("www.")) raw = raw.slice(4);
  raw = raw.trim();
  if (!raw || !raw.includes(".")) return null;
  const label = raw.split(".")[0];
  if (!label) return null;
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function smartTitle(text: string): string {
  if (!text) return text;
  const parts = text.split(/\s+/);
  return parts
    .map((raw, i) => {
      const stripped = raw.replace(/^[()[\]{}.,;:!?]+|[()[\]{}.,;:!?]+$/g, "");
      const prefixLen = raw.length - raw.replace(/^[()[\]{}.,;:!?]+/, "").length;
      const suffixLen = raw.length - raw.replace(/[()[\]{}.,;:!?]+$/, "").length;
      const prefix = raw.slice(0, prefixLen);
      const suffix = suffixLen > 0 ? raw.slice(raw.length - suffixLen) : "";
      const upper = stripped.toUpperCase();
      let rendered: string;
      if (ACRONYMS.has(upper)) {
        rendered = upper;
      } else if (/^\d+$/.test(stripped)) {
        rendered = stripped;
      } else if (i > 0 && LOWERCASE_WORDS.has(stripped.toLowerCase())) {
        rendered = stripped.toLowerCase();
      } else {
        rendered = stripped
          ? stripped.charAt(0).toUpperCase() + stripped.slice(1).toLowerCase()
          : "";
      }
      return `${prefix}${rendered}${suffix}`;
    })
    .join(" ");
}

function truncate(text: string, limit: number = MAX_LEN): string {
  if (text.length <= limit) return text;
  const cut = text.slice(0, limit - 1).replace(/[\s\-:.,]+$/, "");
  return `${cut}\u2026`;
}

function cleanRawName(raw: string): string {
  if (!raw) return "";
  let text = raw.replace(/[\u0000-\u001f\u007f]/g, "");
  for (let i = 0; i < 3; i++) {
    const next = text.replace(PREFIX_RE, "");
    if (next === text) break;
    text = next;
  }
  text = text.replace(META_RE, " ");
  text = text.replace(LONG_ID_RE, " ");
  text = text.replace(MULTISPACE_RE, " ").trim();
  text = text.replace(TRAILING_NUM_RE, "");
  text = text.replace(LEADING_PUNCT_RE, "");
  text = text.replace(TRAILING_PUNCT_RE, "");
  text = text.replace(MULTISPACE_RE, " ").trim();
  if (!text) return "";
  if (!/[a-z]/.test(text)) text = smartTitle(text);
  return text;
}

/**
 * Build a short, human-friendly display title from a transaction or recurring
 * stream. Always returns a non-empty string ("Transaction" as last resort).
 *
 * Prefers the server-supplied `display_title` when present.
 */
export function normalizeTransactionTitle(tx: TitleSource | null | undefined): string {
  if (!tx) return "Transaction";

  const supplied = coerceStr(tx.display_title);
  if (supplied) return supplied;

  const merchant = coerceStr(tx.merchant_name);
  if (merchant && looksPretty(merchant)) return truncate(merchant);

  const cp = fromCounterparties(tx.counterparties ?? null);
  if (cp && looksPretty(cp)) return truncate(cp);

  const site = hostnameFromWebsite(coerceStr(tx.website));
  if (site) return truncate(site);

  const raw = coerceStr(tx.name) || coerceStr(tx.description);
  if (merchant && !raw) return truncate(smartTitle(merchant));
  const cleaned = cleanRawName(raw);
  if (cleaned) return truncate(cleaned);
  if (merchant) return truncate(smartTitle(merchant));
  if (raw) return truncate(smartTitle(raw));
  return "Transaction";
}

/**
 * Returns the raw (untouched) name for use in a `title` attribute / tooltip
 * so the user can hover-inspect the original bank string.
 */
export function rawTransactionTitle(tx: TitleSource | null | undefined): string {
  if (!tx) return "";
  return coerceStr(tx.name) || coerceStr(tx.description) || coerceStr(tx.merchant_name);
}
