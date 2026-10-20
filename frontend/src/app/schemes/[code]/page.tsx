"use client";

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { ExternalLink } from "lucide-react";
import React, { Suspense } from "react";
import { BarList, OutcomeBar, RateCell } from "@/components/charts";
import { GapBadge, PublishedDate } from "@/components/labels";
import { Card, ErrorState, LoadingBlock, PageHeader, Segmented, Stat, Table, Td, Th } from "@/components/ui";
import { label, num, pct, truncate } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Example { id: number; text: string; gap_type: string | null; intent: string | null; source_name: string | null; source_published_at: string | null }
interface Detail {
  scheme: { code: string; name: string; category: string; ministry: string; official_url: string; aliases: string[] };
  overview: { total_records: number; public_voice_records: number; needs_review: number;
    awareness_gap: { yes: number; no: number; unclear: number; not_applicable: number; unlabelled: number; gap_rate: number | null; decided: number } };
  intents: { items: { value: string | null; count: number; share: number | null }[] };
  gap_types: { items: { value: string | null; count: number; share: number | null }[] };
  states: { value: string | null; total: number; yes: number; no: number }[];
  co_mentioned: { scheme: string; count: number }[];
  examples: Record<"yes" | "unclear" | "no", Example[]>;
  misconceptions: { id: number; text: string }[];
}

function SchemeDetail() {
  const { code } = useParams<{ code: string }>();
  const sp = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const scope = (sp.get("scope") as "dataset" | "live") ?? "dataset";
  const { data: d, error, reload } = useApi<Detail>(`/api/schemes/${encodeURIComponent(decodeURIComponent(code))}?scope=${scope}`);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!d) return <LoadingBlock rows={8} />;
  const g = d.overview.awareness_gap;
  const explorer = (extra: string) => `/${scope}/explorer?scheme=${encodeURIComponent(d.scheme.code)}${extra}`;
  return (
    <div className="space-y-5">
      <PageHeader title={d.scheme.code} eyebrow={<Link className="text-xs text-primary hover:underline" href="/schemes">← Schemes</Link>}
        description={<>{d.scheme.name} · {d.scheme.ministry} · <a className="inline-flex items-center gap-1 text-primary hover:underline" href={d.scheme.official_url} target="_blank" rel="noopener noreferrer">official site<ExternalLink className="h-3 w-3" /></a></>}
        actions={<Segmented label="Workspace" value={scope} onChange={(v) => router.replace(`${path}?scope=${v}`)} options={[{ value: "dataset", label: "Dataset" }, { value: "live", label: "Live" }]} />} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Records" value={num(d.overview.total_records)} href={explorer("")} />
        <Stat label="Gap signals" tone="yes" value={num(g.yes)} href={explorer("&awareness_gap=yes")} sub={`of ${num(g.decided)} decided`} />
        <Stat label="Gap rate" tone="yes" value={pct(g.gap_rate)} sub={`n=${num(g.decided)}`} />
        <Stat label="Unclear" tone="unclear" value={num(g.unclear)} href={explorer("&awareness_gap=unclear")} />
      </div>
      <Card title="Gap outcome"><OutcomeBar counts={{ yes: g.yes, no: g.no, unclear: g.unclear, not_applicable: g.not_applicable, unlabelled: g.unlabelled }} /></Card>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Intents"><BarList items={d.intents.items.map((i) => ({ key: i.value ?? "x", label: i.value ? label(i.value) : "Not applicable", value: i.count, share: i.share }))} /></Card>
        <Card title="Gap types"><BarList items={d.gap_types.items.map((i) => ({ key: i.value ?? "x", label: label(i.value ?? "unknown"), value: i.count, share: i.share, color: "var(--gap-yes)" }))} emptyText="No gap signals." /></Card>
        <Card title="Mentioned together with">
          <BarList items={d.co_mentioned.map((c) => ({ key: c.scheme, label: c.scheme, value: c.count, color: "var(--chart-2)", href: `/schemes/${encodeURIComponent(c.scheme)}?scope=${scope}` }))} emptyText="No co-mentions." />
        </Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {(["yes", "unclear"] as const).map((k) => (
          <Card key={k} title={k === "yes" ? "Highest-confidence gap signals" : "Unclear (low model confidence)"}>
            {d.examples[k].length === 0 ? <p className="text-sm text-muted">None.</p> : (
              <ul className="divide-y divide-border">{d.examples[k].map((e) => (
                <li key={e.id} className="py-2">
                  <Link href={`/records/${e.id}`} className="text-sm hover:text-primary hover:underline">{truncate(e.text, 220)}</Link>
                  <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted"><GapBadge value={k} />{label(e.gap_type)} · {e.source_name} · <PublishedDate value={e.source_published_at} /></p>
                </li>))}</ul>
            )}
          </Card>
        ))}
      </div>
      {d.states.filter((s) => s.value).length > 0 && (
        <Card title="States (stated by source)" bodyClassName="p-0 px-4 pb-2">
          <Table caption="Records by state"><thead><tr><Th>State</Th><Th className="text-right">Records</Th><Th>Gap rate</Th></tr></thead>
            <tbody>{d.states.filter((s) => s.value).map((s) => <tr key={s.value}><Td>{s.value}</Td><Td className="text-right tabular">{num(s.total)}</Td><Td><RateCell yes={s.yes} no={s.no} /></Td></tr>)}</tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<LoadingBlock rows={8} />}><SchemeDetail /></Suspense>;
}
