"use client";

import Link from "next/link";
import { Download, Info } from "lucide-react";
import React, { useState } from "react";
import { BarList, OutcomeBar, RateCell, Timeline } from "@/components/charts";
import { FilterBar, Scope, useFilters } from "@/components/filters";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Stat, Table, Td, Th } from "@/components/ui";
import { downloadUrl, qs } from "@/lib/api";
import { dateOnly, label, num, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Overview {
  total_records: number; public_voice_records: number;
  awareness_gap: { yes: number; no: number; unclear: number; not_applicable: number; unlabelled: number; gap_rate: number | null; decided: number };
  schemes_detected: number; unknown_scheme_records: number; states_covered: number; location_coverage: number | null;
  sources: number; needs_review: number; processing: { completed: number; pending: number; failed: number };
  label_sources: Record<string, number>; publication_date_missing: number; published_range: [string | null, string | null];
  collected_range: [string | null, string | null];
  excluded: { duplicates: number; near_duplicates: number; exact_duplicates: number; demo: number; synthetic: number; synthetic_included: boolean };
  definitions: Record<string, string>;
}
interface Dist { total: number; items: { value: string | null; count: number; share: number | null }[] }
interface Breakdown { value: string | null; total: number; public_voice: number; yes: number; no: number; unclear: number; gap_rate: number | null; top_gap_type?: string | null }
interface ClusterList { items: { id: number; name: string; size: number; gap_signals: number; keywords: string[]; low_cohesion: boolean; dominant_scheme: string | null }[] }

export default function AnalyticsView({ scope }: { scope: Scope }) {
  const filters = useFilters(scope);
  const q = filters.query;
  const ov = useApi<Overview>(`/api/analytics/overview${q}`);
  const schemes = useApi<Breakdown[]>(`/api/analytics/schemes${q}`);
  const intents = useApi<Dist>(`/api/analytics/distribution/intent${q}`);
  const gapTypes = useApi<Dist>(`/api/analytics/distribution/gap_type${qs({ ...filters.params, awareness_gap: "yes" })}`);
  const languages = useApi<Dist>(`/api/analytics/distribution/language${q}`);
  const roles = useApi<Dist>(`/api/analytics/distribution/text_role${q}`);
  const timeline = useApi<{ items: { month: string; total: number; yes: number }[]; missing_date: number; date_field: string }>(`/api/analytics/timeline${q}`);
  const clusters = useApi<ClusterList>(`/api/clusters?scope=${scope}&sort=gap_signals`);
  const [showDefs, setShowDefs] = useState(false);
  const o = ov.data;
  const g = o?.awareness_gap;
  const base = `/${scope}/explorer`;
  const link = (extra: Record<string, string>) => `${base}${qs({ ...filters.values, ...extra })}`;

  return (
    <div className="space-y-5">
      <PageHeader
        title={scope === "dataset" ? "Dataset analytics" : "Live collection analytics"}
        description={scope === "dataset"
          ? "Awareness-gap signals in imported datasets. Manual labels are used where supplied; otherwise model predictions."
          : "Awareness-gap signals in records collected from registered public sources, labelled by the trained models."}
        actions={<>
          <Button size="sm" variant="ghost" onClick={() => setShowDefs((x) => !x)} aria-expanded={showDefs}><Info className="h-3.5 w-3.5" />How figures are computed</Button>
          <a href={downloadUrl("/api/documents/export", { ...filters.params, fmt: "csv" })}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2.5 text-xs font-medium hover:bg-surface-2">
            <Download className="h-3.5 w-3.5" aria-hidden />Export filtered CSV
          </a>
        </>}
      />
      {showDefs && o && (
        <Notice tone="info" title="Definitions">
          <ul className="mt-1 list-disc space-y-1 pl-4">
            {Object.entries(o.definitions).map(([k, v]) => <li key={k}><strong>{label(k)}:</strong> {v}</li>)}
          </ul>
        </Notice>
      )}
      <FilterBar scope={scope} filters={filters} compact />

      {ov.error && <ErrorState error={ov.error} onRetry={ov.reload} />}
      {ov.loading && !o && <LoadingBlock rows={3} />}
      {o && o.total_records === 0 && (
        <Card><EmptyState title="No records match">
          {scope === "dataset"
            ? <>Import a labelled CSV or JSON file on the <Link className="text-primary underline" href="/dataset/upload">Import</Link> page, or relax the filters.</>
            : <>Run a collection job from <Link className="text-primary underline" href="/live/campaigns">Collection jobs</Link>, or relax the filters.</>}
        </EmptyState></Card>
      )}

      {o && g && o.total_records > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Unique records" value={num(o.total_records)} href={link({})}
              sub={`${num(o.excluded.duplicates)} duplicates excluded${o.excluded.synthetic && !o.excluded.synthetic_included ? ` · ${num(o.excluded.synthetic)} synthetic excluded` : ""}`} />
            <Stat label="Public-voice records" value={num(o.public_voice_records)} sub="queries, questions, complaints, comments" />
            <Stat label="Gap signals" tone="yes" value={num(g.yes)} href={link({ awareness_gap: "yes" })} sub={`of ${num(g.decided)} decided records`} />
            <Stat label="Gap rate" tone="yes" value={pct(g.gap_rate)} sub={g.decided ? `yes ÷ (yes + no), n=${num(g.decided)}` : "no decided records"} />
            <Stat label="Unclear" tone="unclear" value={num(g.unclear)} href={link({ awareness_gap: "unclear" })} sub="model confidence too low to decide" />
            <Stat label="Location stated" value={pct(o.location_coverage)} sub={`${num(o.states_covered)} states · never inferred`} />
          </div>

          <Card title="Gap outcome across all records in scope"
            description={`${o.published_range[0] ? `Published ${dateOnly(o.published_range[0])} – ${dateOnly(o.published_range[1])} · ` : ""}${num(o.publication_date_missing)} records without a stated publication date`}>
            <OutcomeBar counts={{ yes: g.yes, no: g.no, unclear: g.unclear, not_applicable: g.not_applicable, unlabelled: g.unlabelled }} />
            {o.processing.pending + o.processing.failed > 0 && (
              <p className="mt-3 text-xs text-warning">{num(o.processing.pending)} records awaiting NLP processing, {num(o.processing.failed)} failed.</p>
            )}
          </Card>

          <Card title="Schemes" description="Gap rate is computed only over records with a yes/no decision; n shows that denominator. Rates with n < 5 are greyed."
            bodyClassName="p-0 px-4 pb-2">
            {schemes.error ? <ErrorState error={schemes.error} /> : !schemes.data ? <div className="py-4"><LoadingBlock /></div> : (
              <Table caption="Gap signals by scheme">
                <thead><tr>
                  <Th>Scheme</Th><Th className="text-right">Records</Th><Th className="text-right">Public voice</Th>
                  <Th className="text-right">Gap</Th><Th className="text-right">No gap</Th><Th className="text-right">Unclear</Th>
                  <Th>Gap rate</Th><Th>Most frequent gap type</Th>
                </tr></thead>
                <tbody>{schemes.data.map((r) => (
                  <tr key={r.value ?? "unknown"} className="hover:bg-surface-2/60">
                    <Td>{r.value
                      ? <Link className="hover:text-primary hover:underline" href={`/schemes/${encodeURIComponent(r.value)}?scope=${scope}`}>{r.value}</Link>
                      : <span className="text-subtle">Other / Unknown</span>}</Td>
                    <Td className="text-right tabular">{num(r.total)}</Td>
                    <Td className="text-right tabular">{num(r.public_voice)}</Td>
                    <Td className="text-right tabular text-gap-yes">{num(r.yes)}</Td>
                    <Td className="text-right tabular">{num(r.no)}</Td>
                    <Td className="text-right tabular text-gap-unclear">{num(r.unclear)}</Td>
                    <Td><RateCell yes={r.yes} no={r.no} /></Td>
                    <Td className="text-sm">{r.top_gap_type ? label(r.top_gap_type) : <span className="text-subtle">—</span>}</Td>
                  </tr>
                ))}</tbody>
              </Table>
            )}
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Intent" description="What people ask about (abstentions shown as Unknown).">
              {intents.data ? <BarList items={intents.data.items.map((i) => ({
                key: i.value ?? "none", label: i.value ? label(i.value) : "Not applicable (informational text)",
                value: i.count, share: i.share, href: i.value ? link({ intent: i.value }) : undefined,
              }))} /> : <LoadingBlock />}
            </Card>
            <Card title="Gap types among gap signals" description="Only records with a gap outcome of yes.">
              {gapTypes.data ? <BarList items={gapTypes.data.items.map((i) => ({
                key: i.value ?? "none", label: label(i.value ?? "unknown"), value: i.count, share: i.share,
                color: "var(--gap-yes)", href: i.value ? link({ awareness_gap: "yes", gap_type: i.value }) : undefined,
              }))} emptyText="No gap signals for the current filters." /> : <LoadingBlock />}
            </Card>
          </div>

          <Card title="Over time">
            {timeline.data ? <Timeline items={timeline.data.items} dateField={timeline.data.date_field} missing={timeline.data.missing_date} /> : <LoadingBlock />}
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Recurring themes" description="Largest semantic clusters by gap signals."
              actions={<Link className="text-xs text-primary hover:underline" href={`/${scope}/clusters`}>All clusters</Link>} className="lg:col-span-2">
              {!clusters.data ? <LoadingBlock /> : clusters.data.items.length === 0 ? (
                <p className="text-sm text-muted">No clusters yet. Clustering runs after processing when enough records exist.</p>
              ) : (
                <ul className="divide-y divide-border">
                  {clusters.data.items.slice(0, 6).map((c) => (
                    <li key={c.id} className="flex items-center justify-between gap-3 py-2">
                      <Link href={`/${scope}/clusters?cluster=${c.id}`} className="min-w-0 hover:text-primary">
                        <span className="block truncate text-sm font-medium">{c.name}</span>
                        <span className="text-xs text-muted">{c.dominant_scheme ?? "Mixed schemes"} · {num(c.size)} records</span>
                      </Link>
                      <div className="flex shrink-0 items-center gap-2">
                        {c.low_cohesion && <Badge tone="warning">loose</Badge>}
                        <Badge tone="yes">{num(c.gap_signals)} gap signals</Badge>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Languages & text types">
              <div className="space-y-4">
                {languages.data && <BarList items={languages.data.items.slice(0, 6).map((i) => ({ key: i.value ?? "x", label: label(i.value ?? "und"), value: i.count, share: i.share, color: "var(--chart-2)" }))} />}
                {roles.data && <BarList items={roles.data.items.map((i) => ({ key: i.value ?? "x", label: label(i.value ?? "unknown"), value: i.count, share: i.share, color: "var(--chart-3)" }))} />}
                <p className="text-xs text-muted">The classifiers use a multilingual embedding model and are trained on English, Hindi and romanized-Hindi examples.</p>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
