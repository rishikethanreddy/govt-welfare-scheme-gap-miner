"use client";

import Link from "next/link";
import { Pause, Play } from "lucide-react";
import React, { useState } from "react";
import { CampaignMetrics, EventLog, RecordFeed } from "@/components/CampaignProgress";
import { StatusBadge, Timestamp } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { Badge, Button, Card, LinkButton, LoadingBlock, Notice, PageHeader, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { label, num } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { LiveRecord, useLiveStream } from "@/lib/useLiveStream";

interface Source { id: number; name: string; adapter: string; policy_status: string; active: boolean; verification_status: string;
  last_success_at: string | null; hours_since_success: number | null; last_error: string | null; records_collected: number; schedule: string }

export default function LiveMonitor() {
  const live = useLiveStream("/api/collection/stream", { initialRecords: false });
  const recent = useApi<LiveRecord[]>("/api/collection/feed?limit=20");
  const sources = useApi<Source[]>("/api/sources", { refreshMs: 30000 });
  const [toggling, setToggling] = useState(false);
  const st = live.status;
  const active = st?.active_campaigns ?? [];
  // Show records streamed since the page opened first, then the most recent stored ones.
  const seen = new Set<number>();
  const records = [...live.records, ...(recent.data ?? [])].filter((r) => !seen.has(r.id) && !!seen.add(r.id));

  const toggleAutopilot = async () => {
    setToggling(true);
    try { await api.post(`/api/collection/autopilot?enabled=${!st?.autopilot_enabled}`); } finally { setToggling(false); }
  };
  const enabled = (sources.data ?? []).filter((s) => s.active);

  return (
    <div className="space-y-5">
      <PageHeader title="Live collection monitor"
        description="Real-time view of collection jobs run by the worker. Every count and record below comes from what was actually fetched, persisted and processed."
        actions={<LinkButton href="/live/campaigns" variant="primary">New collection job</LinkButton>} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Worker" description={live.connected ? "Live updates connected" : "Connecting to live updates…"}>
          {!st ? <LoadingBlock rows={3} /> : (
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between"><span className="text-muted">Status</span>
                {st.worker_alive ? <Badge tone="success">{label(st.worker_info?.state ?? "running")}</Badge> : <Badge tone="warning">offline</Badge>}</div>
              <div className="flex items-center justify-between"><span className="text-muted">Last heartbeat</span><Timestamp value={st.last_heartbeat} relativeOnly /></div>
              <div className="flex items-center justify-between"><span className="text-muted">Scheduled collection</span>
                <span className="flex items-center gap-2">{st.autopilot_enabled ? <Badge tone="success">on</Badge> : <Badge>off</Badge>}
                  <OperatorOnly fallback={null}><Button size="sm" variant="ghost" onClick={toggleAutopilot} loading={toggling}>
                    {st.autopilot_enabled ? <><Pause className="h-3.5 w-3.5" />Disable</> : <><Play className="h-3.5 w-3.5" />Enable</>}</Button></OperatorOnly>
                </span></div>
              {!st.worker_alive && <Notice tone="warning">The worker is not running, so queued jobs will not start. Run <code>npm run dev:worker</code> (or <code>python -m backend.worker</code>).</Notice>}
              <p className="text-xs text-muted">When scheduled collection is on, sources marked daily/weekly are collected when due (at most every 12 hours by default).</p>
            </div>
          )}
        </Card>
        <Card title="Active job" className="lg:col-span-2">
          {active.length === 0 ? (
            <p className="text-sm text-muted">No job is running. Start one from <Link className="text-primary hover:underline" href="/live/campaigns">Collection jobs</Link>.</p>
          ) : active.map((c) => (
            <div key={c.id} className="space-y-2">
              <Link href={`/live/campaigns/${c.id}`} className="text-sm font-medium text-primary hover:underline">{c.name}</Link>
              <CampaignMetrics c={c} />
            </div>
          ))}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Activity log" description="Fetches, extraction results, failures and stage changes as they happen.">
          <EventLog events={live.events} empty="Waiting for activity. Events appear here while a job runs." />
        </Card>
        <Card title="Newly processed records" description="Records appear once they are persisted and labelled.">
          <RecordFeed records={records} />
        </Card>
      </div>

      <Card title="Source freshness" bodyClassName="p-0 px-4 pb-2" actions={<Link className="text-xs text-primary hover:underline" href="/live/sources">Manage sources</Link>}>
        {!sources.data ? <div className="py-4"><LoadingBlock /></div> : (
          <Table caption="Enabled sources and their last successful collection">
            <thead><tr><Th>Source</Th><Th>Verification</Th><Th>Last success</Th><Th className="text-right">Records</Th><Th>Schedule</Th><Th>Last error</Th></tr></thead>
            <tbody>{enabled.map((s) => (
              <tr key={s.id}>
                <Td className="font-medium">{s.name}</Td>
                <Td><StatusBadge status={s.verification_status} /></Td>
                <Td className="text-xs">{s.last_success_at ? <Timestamp value={s.last_success_at} relativeOnly /> : <span className="text-subtle">never</span>}</Td>
                <Td className="text-right tabular">{num(s.records_collected)}</Td>
                <Td className="text-xs">{s.schedule}</Td>
                <Td className="max-w-xs truncate text-xs text-danger" title={s.last_error ?? undefined}>{s.last_error ?? ""}</Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
