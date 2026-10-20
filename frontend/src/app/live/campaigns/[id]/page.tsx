"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import React, { useState } from "react";
import { CampaignMetrics, EventLog, RecordFeed } from "@/components/CampaignProgress";
import { StatusBadge, Timestamp } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { Button, Card, ErrorState, LoadingBlock, Notice, PageHeader, Segmented, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { num, truncate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { RecordRow } from "@/components/RecordTable";
import { LiveEvent, LiveRecord, useLiveStream } from "@/lib/useLiveStream";

interface Detail { id: number; name: string; status: string; url_status: Record<string, number>;
  source_runs: { source_id: number; source_name: string; status: string; successful: number; failed: number; blocked: number;
    records_accepted: number; duplicates: number; rejected: number; error: string | null; started_at: string; finished_at: string | null }[] }
interface Url { id: number; url: string; status: string; http_status: number | null; depth: number; discovery_method: string; records_extracted: number; error: string | null }

const ACTIVE = ["queued", "running", "cancel_requested"];

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const detail = useApi<Detail>(`/api/collection/campaigns/${id}`, { refreshMs: 5000 });
  const live = useLiveStream(`/api/collection/campaigns/${id}/stream`);
  const history = useApi<LiveEvent[]>(`/api/collection/campaigns/${id}/events?limit=500`);
  const records = useApi<{ items: RecordRow[] }>(`/api/documents?scope=live&campaign_id=${id}&page_size=30&sort_by=id&sort_order=desc`, { refreshMs: 8000 });
  const [urlStatus, setUrlStatus] = useState("failed");
  const urls = useApi<Url[]>(`/api/collection/campaigns/${id}/urls?status=${urlStatus}&limit=200`);
  const [busy, setBusy] = useState<string>();
  const [msg, setMsg] = useState<string>();
  const c = live.campaign;
  const d = detail.data;

  const act = async (what: "cancel" | "retry-failed") => {
    setBusy(what); setMsg(undefined);
    try { await api.post(`/api/collection/campaigns/${id}/${what}`); detail.reload(); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(undefined); }
  };
  // Live events first (newest), then stored history not yet seen in this session.
  const ids = new Set(live.events.map((e) => e.id));
  const events = [...live.events, ...[...(history.data ?? [])].reverse().filter((e) => !ids.has(e.id))];
  const feed: LiveRecord[] = (records.data?.items ?? []).map((r) => ({
    id: r.id, text: r.original_text, scheme: r.scheme_name, text_role: r.text_role, intent: r.intent,
    awareness_gap: r.awareness_gap, gap_type: r.gap_type, language: r.language, source_name: r.source_name,
    source_url: r.source_url ?? null, source_published_at: r.source_published_at, collected_at: r.collected_at,
    processed_at: null, campaign_id: Number(id),
  }));

  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.reload} />;
  if (!d) return <LoadingBlock rows={8} />;
  const status = c?.status ?? d.status;
  return (
    <div className="space-y-5">
      <PageHeader title={d.name} eyebrow={<Link href="/live/campaigns" className="text-xs text-primary hover:underline">← Collection jobs</Link>}
        actions={<OperatorOnly fallback={null}>
          {ACTIVE.includes(status) && <Button variant="danger" size="sm" loading={busy === "cancel"} onClick={() => act("cancel")}>Cancel job</Button>}
          {!ACTIVE.includes(status) && (d.url_status.failed ?? 0) > 0 && <Button size="sm" loading={busy === "retry-failed"} onClick={() => act("retry-failed")}>Retry {d.url_status.failed} failed URLs</Button>}
        </OperatorOnly>} />
      {msg && <Notice tone="danger">{msg}</Notice>}
      {status === "queued" && <Notice tone="info">Queued — it starts when the worker picks it up. If nothing happens, check that the worker is running.</Notice>}
      <Card title="Progress" description={live.connected ? "Live" : live.ended ? "Job finished" : "Connecting…"}>
        {c ? <CampaignMetrics c={c} /> : <LoadingBlock rows={3} />}
      </Card>
      <Card title="Sources in this job" bodyClassName="p-0 px-4 pb-2">
        <Table caption="Per-source results">
          <thead><tr><Th>Source</Th><Th>Status</Th><Th className="text-right">Fetched</Th><Th className="text-right">Failed</Th><Th className="text-right">Blocked</Th><Th className="text-right">New</Th><Th className="text-right">Dupes</Th><Th className="text-right">Rejected</Th><Th>Error</Th></tr></thead>
          <tbody>{d.source_runs.map((r) => (
            <tr key={r.source_id}>
              <Td className="font-medium">{r.source_name}</Td><Td><StatusBadge status={r.status} /></Td>
              <Td className="text-right tabular">{num(r.successful)}</Td><Td className="text-right tabular">{num(r.failed)}</Td>
              <Td className="text-right tabular">{num(r.blocked)}</Td><Td className="text-right tabular">{num(r.records_accepted)}</Td>
              <Td className="text-right tabular">{num(r.duplicates)}</Td><Td className="text-right tabular">{num(r.rejected)}</Td>
              <Td className="max-w-xs truncate text-xs text-danger" title={r.error ?? undefined}>{r.error ?? ""}</Td>
            </tr>
          ))}</tbody>
        </Table>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Activity log"><EventLog events={events} /></Card>
        <Card title="Records from this job" actions={<Link className="text-xs text-primary hover:underline" href={`/live/explorer?campaign_id=${id}`}>All records</Link>}>
          <RecordFeed records={feed} empty="No new records were stored by this job." />
        </Card>
      </div>
      <Card title="URLs" actions={<Segmented label="URL status" value={urlStatus} onChange={setUrlStatus}
        options={Object.keys(d.url_status).sort().map((s) => ({ value: s, label: `${s} (${d.url_status[s]})` }))} />} bodyClassName="p-0 px-4 pb-2">
        {!urls.data ? <div className="py-4"><LoadingBlock /></div> : (
          <Table caption="URLs by status">
            <thead><tr><Th>URL</Th><Th>HTTP</Th><Th>Found via</Th><Th>Depth</Th><Th className="text-right">Records</Th><Th>Error</Th></tr></thead>
            <tbody>{urls.data.map((u) => (
              <tr key={u.id}>
                <Td className="max-w-md"><a href={u.url} target="_blank" rel="noopener noreferrer" className="break-all text-xs text-primary hover:underline">{truncate(u.url, 110)}</a></Td>
                <Td className="tabular text-xs">{u.http_status ?? "—"}</Td><Td className="text-xs">{u.discovery_method}</Td><Td className="tabular text-xs">{u.depth}</Td>
                <Td className="text-right tabular text-xs">{u.records_extracted}</Td>
                <Td className="max-w-xs text-xs text-danger">{u.error ?? ""}</Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      {c && <p className="text-xs text-subtle">Last worker heartbeat <Timestamp value={c.heartbeat_at} /></p>}
    </div>
  );
}
