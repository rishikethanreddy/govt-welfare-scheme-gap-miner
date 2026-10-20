"use client";

import { Badge, Tone } from "@/components/ui";
import { dateTime, label, relative, schemeLabel } from "@/lib/format";

export function GapBadge({ value, confidence }: { value: string | null | undefined; confidence?: number | null }) {
  const tone: Tone = value === "yes" ? "yes" : value === "no" ? "no" : value === "unclear" ? "unclear" : "na";
  return (
    <Badge tone={tone} title={confidence != null ? `Model confidence ${(confidence * 100).toFixed(0)}%` : undefined}>
      {value ? label(value) : "Not processed"}
      {confidence != null && <span className="opacity-70 tabular">{(confidence * 100).toFixed(0)}%</span>}
    </Badge>
  );
}

export function LabelSourceBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  const tone: Tone = value === "manual" ? "success" : value === "review" ? "info" : "neutral";
  return <Badge tone={tone}>{label(value)}</Badge>;
}

export function SchemeTag({ value, strength }: { value: string | null | undefined; strength?: string | null }) {
  return (
    <span className="inline-flex items-center gap-1 text-sm" title={strength ? `Match: ${strength}` : undefined}>
      <span className={value ? "text-foreground" : "text-subtle"}>{schemeLabel(value)}</span>
      {strength === "weak" && <Badge tone="warning">weak match</Badge>}
      {strength === "context" && <Badge tone="neutral">from page</Badge>}
    </span>
  );
}

/** A source-stated date, or an explicit "unavailable" marker — never the crawl time. */
export function PublishedDate({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-xs italic text-subtle">Publication date unavailable</span>;
  return <time dateTime={value} title={dateTime(value)} className="tabular">{dateTime(value)}</time>;
}

export function Timestamp({ value, relativeOnly }: { value: string | null | undefined; relativeOnly?: boolean }) {
  if (!value) return <span className="text-subtle">—</span>;
  return (
    <time dateTime={value} title={dateTime(value)} className="tabular">
      {relativeOnly ? relative(value) : dateTime(value)}
    </time>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  const tone: Tone =
    ["completed", "collected", "allowed", "success", "healthy", "connected", "processed"].includes(s) ? "success" :
    ["running", "queued", "processing", "pending", "reachable", "cancel_requested"].includes(s) ? "info" :
    ["completed_with_errors", "manual_review", "paused", "unchanged", "partial", "degraded", "credentials_required"].includes(s) ? "warning" :
    ["failed", "failing", "blocked", "unreachable"].includes(s) ? "danger" : "neutral";
  return <Badge tone={tone}>{label(s)}</Badge>;
}
