"use client";

import Link from "next/link";
import { ArrowRight, Database, Radio } from "lucide-react";
import React from "react";
import { OutcomeBar } from "@/components/charts";
import { StatusBadge, Timestamp } from "@/components/labels";
import { Card, ErrorState, KeyValue, LoadingBlock, PageHeader } from "@/components/ui";
import { dateOnly, duration, num, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Overview {
  total_records: number; public_voice_records: number; sources: number; needs_review: number;
  awareness_gap: { yes: number; no: number; unclear: number; not_applicable: number; unlabelled: number; gap_rate: number | null; decided: number };
  schemes_detected: number; location_coverage: number | null; published_range: [string | null, string | null];
  excluded: { duplicates: number; synthetic: number };
}
interface Campaign { id: number; name: string; status: string; metrics: Record<string, number>; crawl_started_at: string | null; crawl_finished_at: string | null; elapsed_seconds: number | null }

function Workspace({ scope, title, icon, children }: { scope: "dataset" | "live"; title: string; icon: React.ReactNode; children?: React.ReactNode }) {
  const { data: o, error, reload } = useApi<Overview>(`/api/analytics/overview?scope=${scope}`);
  const g = o?.awareness_gap;
  return (
    <Card title={<span className="flex items-center gap-2">{icon}{title}</span>}
      actions={<Link href={`/${scope}/analytics`} className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">Open analytics<ArrowRight className="h-3 w-3" /></Link>}>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!o && !error && <LoadingBlock rows={5} />}
      {o && g && (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[["Unique records", num(o.total_records)], ["Public-voice", num(o.public_voice_records)],
              ["Gap signals", num(g.yes)], ["Gap rate", g.decided ? `${pct(g.gap_rate)}` : "—"]].map(([k, v]) => (
              <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="text-xl font-semibold tabular">{v}</dd></div>
            ))}
          </dl>
          <OutcomeBar counts={{ yes: g.yes, no: g.no, unclear: g.unclear, not_applicable: g.not_applicable, unlabelled: g.unlabelled }} />
          <p className="text-xs text-muted">
            Gap rate n = {num(g.decided)} decided records · {num(o.excluded.duplicates)} duplicates excluded
            {o.published_range[0] && <> · published {dateOnly(o.published_range[0])} – {dateOnly(o.published_range[1])}</>}
          </p>
          {children}
        </div>
      )}
    </Card>
  );
}

export default function OverviewPage() {
  const campaigns = useApi<{ items: Campaign[] }>("/api/collection/campaigns?limit=1", { refreshMs: 15000 });
  const last = campaigns.data?.items[0];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Welfare scheme awareness-gap signals"
        description="Public questions, complaints and comments about Indian welfare schemes, analysed for recurring signs that people lack or misunderstand scheme information. Imported datasets and live-collected records are kept in separate workspaces."
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <Workspace scope="dataset" title="Dataset workspace" icon={<Database className="h-4 w-4 text-primary" aria-hidden />} />
        <Workspace scope="live" title="Live collection workspace" icon={<Radio className="h-4 w-4 text-info" aria-hidden />} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Latest collection job" actions={<Link className="text-xs text-primary hover:underline" href="/live/campaigns">All jobs</Link>}>
          {!last ? <p className="text-sm text-muted">No collection jobs yet.</p> : (
            <KeyValue items={[
              ["Job", <Link key="j" className="hover:text-primary hover:underline" href={`/live/campaigns/${last.id}`}>{last.name}</Link>],
              ["Status", <StatusBadge key="s" status={last.status} />],
              ["Started", <Timestamp key="t" value={last.crawl_started_at} />],
              ["Duration", duration(last.elapsed_seconds)],
              ["New records", num(last.metrics.records_final)],
              ["Failed / blocked URLs", `${num(last.metrics.urls_failed)} / ${num(last.metrics.urls_blocked)}`],
            ]} />
          )}
        </Card>
        <Card title="Reading these figures">
          <ul className="list-disc space-y-1.5 pl-4 text-sm text-muted">
            <li>A <strong className="text-foreground">gap signal</strong> is a public question or comment that indicates missing or incorrect scheme information. A question alone is not a gap.</li>
            <li>English, Hindi and romanized Hindi are all classified. A record is <strong className="text-foreground">unclear</strong> only when the model&apos;s confidence falls inside a narrow uncertainty band or the text is unlike any labelled example.</li>
            <li>News, FAQ entries and articles are informational and marked <strong className="text-foreground">not applicable</strong>.</li>
            <li>Results describe the analysed text, not population-wide awareness.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
