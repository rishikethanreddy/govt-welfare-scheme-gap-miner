"use client";

import React, { useState } from "react";
import { StatusBadge, Timestamp } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { Badge, Button, Card, Checkbox, Dialog, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { label, num } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Source { id: number; name: string; url: string; source_type: string; category: string | null; adapter: string;
  policy_status: string; policy_note: string | null; active: boolean; schedule: string; max_pages: number | null;
  verification_status: string; last_run_at: string | null; last_success_at: string | null; hours_since_success: number | null;
  last_error: string | null; consecutive_failures: number; health_score: number | null; total_runs: number; records_collected: number }

function AddSource({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", adapter: "html", source_type: "official", max_pages: 20 });
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setError(undefined);
    try { await api.post("/api/sources", form); setOpen(false); onDone(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>Register source</Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Register a public source"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={busy} onClick={submit}>Register</Button></>}>
        <div className="space-y-3">
          <Notice tone="info">New sources start disabled. The URL is checked for safety (public address, http/https) and against robots.txt; review the site&apos;s terms of use before enabling it.</Notice>
          <Field label="Name" htmlFor="s-name"><Input id="s-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="URL" htmlFor="s-url"><Input id="s-url" type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Adapter" htmlFor="s-ad"><Select id="s-ad" value={form.adapter} onChange={(e) => setForm({ ...form, adapter: e.target.value })}
              options={["html", "rss", "sitemap", "json_api", "csv"].map((v) => ({ value: v, label: v }))} /></Field>
            <Field label="Type" htmlFor="s-type"><Select id="s-type" value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value })}
              options={["official", "open_data", "news", "publication", "other"].map((v) => ({ value: v, label: v }))} /></Field>
            <Field label="Max pages" htmlFor="s-max"><Input id="s-max" type="number" min={1} max={500} value={form.max_pages} onChange={(e) => setForm({ ...form, max_pages: Number(e.target.value) })} /></Field>
          </div>
          {error && <Notice tone="danger">{error}</Notice>}
        </div>
      </Dialog>
    </>
  );
}

export default function SourcesPage() {
  const [retired, setRetired] = useState(false);
  const list = useApi<Source[]>(`/api/sources?include_retired=${retired}`, { refreshMs: 30000 });
  const [busy, setBusy] = useState<string>();
  const [checks, setChecks] = useState<Record<number, string>>({});
  const [error, setError] = useState<string>();

  const toggle = async (s: Source) => {
    setBusy(`t${s.id}`); setError(undefined);
    try { await api.patch(`/api/sources/${s.id}`, { active: !s.active }); list.reload(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(undefined); }
  };
  const check = async (s: Source) => {
    setBusy(`c${s.id}`);
    try {
      const r = await api.post<{ ok: boolean; status?: number; content_type?: string; error?: string; error_kind?: string }>(`/api/sources/${s.id}/check`);
      setChecks((c) => ({ ...c, [s.id]: r.ok ? `OK · HTTP ${r.status} · ${r.content_type}` : `Failed · ${r.error_kind ?? ""} ${r.error ?? `HTTP ${r.status}`}` }));
    } catch (e) { setChecks((c) => ({ ...c, [s.id]: (e as Error).message })); } finally { setBusy(undefined); }
  };
  const sync = async () => {
    setBusy("sync");
    try { await api.post("/api/sources/sync"); list.reload(); } finally { setBusy(undefined); }
  };

  const groups = ["allowed", "paused", "credentials_required", "manual_review", "unsupported", "blocked", "retired"];
  const sorted = [...(list.data ?? [])].sort((a, b) => groups.indexOf(a.policy_status) - groups.indexOf(b.policy_status) || a.name.localeCompare(b.name));

  return (
    <div className="space-y-5">
      <PageHeader title="Source registry"
        description="Every source records why it is or is not collected. Verification status reflects real runs only: configured → reachable → collected, or failing/blocked. Sources pause automatically after repeated failures."
        actions={<OperatorOnly fallback={null}><Button size="sm" variant="ghost" loading={busy === "sync"} onClick={sync}>Sync curated registry</Button><AddSource onDone={list.reload} /></OperatorOnly>} />
      {error && <Notice tone="danger">{error}</Notice>}
      <Card bodyClassName="p-0 px-4 pb-2" title={list.data ? `${list.data.length} sources` : "Sources"}
        actions={<Checkbox label="Show retired" checked={retired} onChange={(e) => setRetired(e.target.checked)} />}>
        {list.error && <div className="py-3"><ErrorState error={list.error} onRetry={list.reload} /></div>}
        {!list.data ? <div className="py-4"><LoadingBlock rows={6} /></div> : (
          <Table caption="Registered sources">
            <thead><tr><Th>Source</Th><Th>Policy</Th><Th>Verification</Th><Th>Last success</Th><Th className="text-right">Records</Th><Th className="text-right">Runs</Th><Th>Controls</Th></tr></thead>
            <tbody>{sorted.map((s) => (
              <tr key={s.id} className="align-top">
                <Td className="max-w-md">
                  <span className="font-medium">{s.name}</span>
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="block break-all text-xs text-primary hover:underline">{s.url}</a>
                  <span className="mt-1 flex flex-wrap gap-1"><Badge>{s.adapter}</Badge><Badge>{s.source_type}</Badge>{s.schedule !== "manual" && <Badge>{s.schedule}</Badge>}</span>
                  {s.policy_note && <p className="mt-1 text-xs text-muted">{s.policy_note}</p>}
                  {s.last_error && <p className="mt-1 text-xs text-danger">Last error: {s.last_error}</p>}
                  {checks[s.id] && <p className="mt-1 text-xs text-info">Check: {checks[s.id]}</p>}
                </Td>
                <Td><StatusBadge status={s.policy_status} />{s.active && <span className="mt-1 block text-[11px] text-success">enabled</span>}</Td>
                <Td><StatusBadge status={s.verification_status} />{s.consecutive_failures > 0 && <span className="mt-1 block text-[11px] text-danger">{s.consecutive_failures} failed runs</span>}</Td>
                <Td className="text-xs">{s.last_success_at ? <Timestamp value={s.last_success_at} relativeOnly /> : <span className="text-subtle">never</span>}</Td>
                <Td className="text-right tabular">{num(s.records_collected)}</Td>
                <Td className="text-right tabular">{num(s.total_runs)}</Td>
                <Td>
                  <OperatorOnly fallback={<span className="text-xs text-subtle">{label(s.policy_status)}</span>}>
                    <div className="flex flex-col items-start gap-1">
                      {["allowed", "paused", "manual_review"].includes(s.policy_status) && (
                        <Button size="sm" variant={s.active ? "secondary" : "primary"} loading={busy === `t${s.id}`} onClick={() => toggle(s)}>{s.active ? "Disable" : "Enable"}</Button>
                      )}
                      {s.policy_status !== "blocked" && s.policy_status !== "retired" && (
                        <Button size="sm" variant="ghost" loading={busy === `c${s.id}`} onClick={() => check(s)}>Test fetch</Button>
                      )}
                    </div>
                  </OperatorOnly>
                </Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
