"use client";

import Link from "next/link";
import React from "react";
import { GapBadge, PublishedDate, StatusBadge, Timestamp } from "@/components/labels";
import { Badge } from "@/components/ui";
import { duration, label, num, truncate } from "@/lib/format";
import type { CampaignSnapshot, LiveEvent, LiveRecord } from "@/lib/useLiveStream";
import { cn } from "@/lib/utils";

export function CampaignMetrics({ c }: { c: CampaignSnapshot }) {
  const m = c.metrics;
  const stages: [string, number, string?][] = [
    ["URLs discovered", m.urls_discovered], ["URLs processed", m.urls_processed],
    ["Unchanged", m.urls_unchanged, "same content as last collection"], ["Failed", m.urls_failed], ["Blocked", m.urls_blocked, "robots.txt, HTTP 401/403 or unsafe URL"],
    ["Candidate records", m.records_extracted], ["Duplicates", m.records_duplicate], ["Rejected", m.records_rejected, "invalid or off-topic"],
    ["New records", m.records_final], ["NLP processed", m.records_processed],
  ];
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <StatusBadge status={c.status} />
        {c.stage && <span className="text-muted">Stage: {label(c.stage)}</span>}
        <span className="text-muted">Started <Timestamp value={c.crawl_started_at} /></span>
        {c.crawl_finished_at && <span className="text-muted">Finished <Timestamp value={c.crawl_finished_at} /></span>}
        <span className="tabular text-muted">Elapsed {duration(c.elapsed_seconds)}</span>
      </div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {stages.map(([k, v, hint]) => (
          <div key={k} className="rounded-md border border-border px-3 py-2" title={hint}>
            <dt className="text-[11px] text-muted">{k}</dt>
            <dd className={cn("text-lg font-semibold tabular", (k === "Failed" || k === "Blocked") && v ? "text-danger" : k === "New records" && v ? "text-success" : "")}>{num(v)}</dd>
          </div>
        ))}
      </dl>
      {c.error_message && <p className="mt-2 text-xs text-warning">{c.error_message}</p>}
    </div>
  );
}

export function EventLog({ events, empty = "No activity yet." }: { events: LiveEvent[]; empty?: string }) {
  if (!events.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ol className="scrollbar-thin max-h-[28rem] space-y-1 overflow-y-auto font-mono text-xs" aria-live="polite" aria-relevant="additions">
      {events.map((e) => (
        <li key={e.id} className={cn("flex gap-2 rounded px-1.5 py-1",
          e.level === "error" ? "bg-danger-soft text-danger" : e.level === "warning" ? "text-warning" : "text-foreground")}>
          <time className="shrink-0 text-subtle" dateTime={e.created_at}>{new Date(e.created_at).toLocaleTimeString()}</time>
          <span className="shrink-0 text-subtle">{e.kind}</span>
          <span className="min-w-0 break-words">
            {e.document_id ? <Link className="hover:underline" href={`/records/${e.document_id}`}>{e.message}</Link> : e.message}
            {e.url && <span className="block truncate text-subtle">{e.url}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function RecordFeed({ records, empty = "No records collected yet." }: { records: LiveRecord[]; empty?: string }) {
  if (!records.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="scrollbar-thin max-h-[28rem] divide-y divide-border overflow-y-auto">
      {records.map((r) => (
        <li key={r.id} className="py-2.5">
          <Link href={`/records/${r.id}`} className="text-sm text-foreground hover:text-primary hover:underline">{truncate(r.text, 200)}</Link>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <GapBadge value={r.awareness_gap} />
            <Badge>{r.scheme ?? "Other / Unknown"}</Badge>
            <Badge>{label(r.text_role)}</Badge>
            <span>{r.source_name}</span>
            <span>· published <PublishedDate value={r.source_published_at} /></span>
            <span>· collected <Timestamp value={r.collected_at} relativeOnly /></span>
          </div>
        </li>
      ))}
    </ul>
  );
}
