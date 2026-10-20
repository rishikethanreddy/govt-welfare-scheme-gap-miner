/** Formatting helpers. All timestamps from the API are UTC (ISO 8601 with offset);
 *  they are rendered in the viewer's local timezone. */

const nf = new Intl.NumberFormat("en-IN");

export function num(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : nf.format(n);
}

export function pct(share: number | null | undefined, digits = 0): string {
  if (share === null || share === undefined || Number.isNaN(share)) return "—";
  return `${(share * 100).toFixed(digits)}%`;
}

export function toDate(v: string | null | undefined): Date | null {
  if (!v) return null;
  // Backend values always carry an offset; treat a bare timestamp as UTC to be safe.
  const s = /[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function dateTime(v: string | null | undefined): string {
  const d = toDate(v);
  return d ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
}

export function dateOnly(v: string | null | undefined): string {
  const d = toDate(v);
  return d ? d.toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
}

export function relative(v: string | null | undefined): string {
  const d = toDate(v);
  if (!d) return "—";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  const abs = Math.abs(s);
  const fmt = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (abs < 60) return fmt.format(-s, "second");
  if (abs < 3600) return fmt.format(-Math.round(s / 60), "minute");
  if (abs < 86400) return fmt.format(-Math.round(s / 3600), "hour");
  if (abs < 86400 * 45) return fmt.format(-Math.round(s / 86400), "day");
  if (abs < 86400 * 365) return fmt.format(-Math.round(s / (86400 * 30)), "month");
  return fmt.format(-Math.round(s / (86400 * 365)), "year");
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ${seconds % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export const timezoneName = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

const LABELS: Record<string, string> = {
  yes: "Gap signal",
  no: "No gap",
  unclear: "Unclear",
  not_applicable: "Not applicable",
  eligibility: "Eligibility",
  application: "Application",
  documentation: "Documentation",
  benefits: "Benefits",
  payment: "Payment",
  deadline: "Deadline",
  complaint: "Complaint",
  general_information: "General information",
  unknown: "Unknown",
  eligibility_gap: "Eligibility gap",
  application_gap: "Application gap",
  documentation_gap: "Documentation gap",
  benefit_gap: "Benefit gap",
  payment_gap: "Payment gap",
  deadline_gap: "Deadline gap",
  misconception: "Misconception",
  none: "None",
  query: "Query",
  question: "Question",
  discussion: "Public comment",
  site_reply: "Site reply",
  faq: "FAQ entry",
  news: "News item",
  article: "Article",
  paragraph: "Paragraph",
  manual: "Manual label",
  review: "Reviewed",
  model: "Model prediction",
  en: "English",
  hi: "Hindi",
  "hi-Latn": "Hindi (romanized)",
  "mr-Latn": "Marathi (romanized)",
  und: "Undetermined",
  bn: "Bengali",
  gu: "Gujarati",
  ta: "Tamil",
  te: "Telugu",
  mr: "Marathi",
  pa: "Punjabi",
  kn: "Kannada",
  ml: "Malayalam",
  or: "Odia",
};

export function label(v: string | null | undefined, fallback = "—"): string {
  if (v === null || v === undefined || v === "") return fallback;
  return LABELS[v] ?? v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function schemeLabel(v: string | null | undefined): string {
  return v ?? "Other / Unknown";
}

export function truncate(s: string | null | undefined, n = 140): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
