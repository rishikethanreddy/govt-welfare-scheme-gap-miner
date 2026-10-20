"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useState } from "react";
import { StatusBadge, Timestamp } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { duration, num } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CampaignSnapshot } from "@/lib/useLiveStream";

interface Source { id: number; name: string; adapter: string; active: boolean; policy_status: string; verification_status: string; max_pages: number | null }

function NewJob() {
  const router = useRouter();
  const sources = useApi<Source[]>("/api/sources");
  const usable = (sources.data ?? []).filter((s) => s.active && s.policy_status === "allowed");
  const [picked, setPicked] = useState<number[]>([]);
  const [name, setName] = useState("Manual collection");
  const [pages, setPages] = useState(15);
  const [depth, setDepth] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const submit = async () => {
    setBusy(true); setError(undefined);
    try {
      const c = await api.post<CampaignSnapshot>("/api/collection/campaigns",
        { name, source_ids: picked.length ? picked : null, max_pages_per_source: pages, max_depth: depth });
      router.push(`/live/campaigns/${c.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  if (sources.loading) return <LoadingBlock rows={3} />;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Job name" htmlFor="job-name"><Input id="job-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Max pages per source" htmlFor="job-pages" hint="The source's own limit applies if lower.">
          <Input id="job-pages" type="number" min={1} max={200} value={pages} onChange={(e) => setPages(Number(e.target.value))} /></Field>
        <Field label="Link depth" htmlFor="job-depth" hint="0 = seed pages only; 1 = also follow relevant links once.">
          <Input id="job-depth" type="number" min={0} max={3} value={depth} onChange={(e) => setDepth(Number(e.target.value))} /></Field>
      </div>
      <fieldset>
        <legend className="mb-2 text-xs font-medium text-muted">Sources ({usable.length} enabled; none selected = all enabled sources)</legend>
        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {usable.map((s) => (
            <Checkbox key={s.id} label={`${s.name} (${s.adapter})`} checked={picked.includes(s.id)}
              onChange={(e) => setPicked((p) => e.target.checked ? [...p, s.id] : p.filter((x) => x !== s.id))} />
          ))}
        </div>
      </fieldset>
      {error && <Notice tone="danger">{error}</Notice>}
      <Button variant="primary" onClick={submit} loading={busy} disabled={!name.trim() || !usable.length}>Queue job</Button>
      <p className="text-xs text-muted">Jobs are executed by the worker process. Requests respect robots.txt, per-host delays, size limits and SSRF protection.</p>
    </div>
  );
}

export default function CampaignsPage() {
  const [archived, setArchived] = useState(false);
  const list = useApi<{ items: CampaignSnapshot[]; archived_count: number }>(`/api/collection/campaigns?include_archived=${archived}&limit=100`, { refreshMs: 10000 });
  return (
    <div className="space-y-5">
      <PageHeader title="Collection jobs" description="Each job collects from the selected registered sources. Metrics are counted from actual fetches and stored records." />
      <Card title="New collection job">
        <OperatorOnly fallback={<p className="text-sm text-muted">Operator access is required to start collection.</p>}><NewJob /></OperatorOnly>
      </Card>
      <Card title="History" bodyClassName="p-0 px-4 pb-2"
        actions={list.data?.archived_count ? <Checkbox label={`Show ${num(list.data.archived_count)} archived`} checked={archived} onChange={(e) => setArchived(e.target.checked)} /> : undefined}>
        {list.error && <div className="py-3"><ErrorState error={list.error} onRetry={list.reload} /></div>}
        {!list.data ? <div className="py-4"><LoadingBlock /></div> : list.data.items.length === 0 ? <EmptyState title="No collection jobs yet" /> : (
          <Table caption="Collection jobs">
            <thead><tr><Th>Job</Th><Th>Status</Th><Th>Started</Th><Th>Duration</Th><Th className="text-right">URLs</Th><Th className="text-right">Failed</Th><Th className="text-right">New records</Th><Th className="text-right">Duplicates</Th></tr></thead>
            <tbody>{list.data.items.map((c) => (
              <tr key={c.id} className="hover:bg-surface-2/60">
                <Td><Link className="font-medium hover:text-primary hover:underline" href={`/live/campaigns/${c.id}`}>{c.name}</Link><span className="block text-xs text-subtle">#{c.id}</span></Td>
                <Td><StatusBadge status={c.status} /></Td>
                <Td className="text-xs"><Timestamp value={c.crawl_started_at} /></Td>
                <Td className="tabular text-xs">{duration(c.elapsed_seconds)}</Td>
                <Td className="text-right tabular">{num(c.metrics.urls_processed)}</Td>
                <Td className="text-right tabular">{num(c.metrics.urls_failed + c.metrics.urls_blocked)}</Td>
                <Td className="text-right tabular">{num(c.metrics.records_final)}</Td>
                <Td className="text-right tabular">{num(c.metrics.records_duplicate)}</Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
