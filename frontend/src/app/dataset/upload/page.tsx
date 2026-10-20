"use client";

import Link from "next/link";
import { FileUp, RefreshCw } from "lucide-react";
import React, { useEffect, useState } from "react";
import { StatusBadge, Timestamp } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select, Table, Td, Th } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { num } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Preview { columns: string[]; row_count: number; mapping: Record<string, string | null>; sample: Record<string, string | null>[]; missing_text_column: boolean }
interface Job { id: number; status: string; progress: number; total_items: number | null; processed_items: number; failed_items: number; error: string | null;
  result: { processed?: number; failed?: number; near_duplicates?: number; clustering?: { status: string; clusters?: number; reason?: string } } | null }
interface Dataset { id: number; version: string; name: string; source_file: string; record_count: number; valid_records: number;
  duplicate_records: number; rejected_records: number; processed_records: number; processing_status: string; created_at: string;
  file_sha256: string | null; job: Job | null }

const FIELDS: [string, string, string][] = [
  ["text", "Text *", "The question / complaint / comment"],
  ["scheme", "Scheme", "Manual scheme label (optional)"],
  ["intent", "Intent", "Manual intent label (optional)"],
  ["awareness_gap", "Awareness gap", "yes / no / unclear (optional)"],
  ["gap_type", "Gap type", "Manual gap type (optional)"],
  ["state", "State", "Only if the source states it"],
  ["district", "District", "Only if the source states it"],
  ["source", "Source name", ""],
  ["source_url", "Source URL", ""],
  ["published_at", "Publication date", "Date the text was originally written"],
  ["text_role", "Text type", "query / complaint / faq / news …"],
  ["split", "Split", "train / val / test"],
  ["is_synthetic", "Synthetic flag", "yes/true marks generated records"],
  ["id", "Row id", ""],
];

function JobProgress({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const { data: j } = useApi<Job>(`/api/jobs/${jobId}`, { refreshMs: 1500 });
  const finished = !!j && ["completed", "failed"].includes(j.status);
  useEffect(() => {
    if (finished) onDone();
  }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!j) return <LoadingBlock rows={1} />;
  const pctDone = Math.round((j.progress ?? 0) * 100);
  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-center justify-between text-sm">
        <span>NLP processing job #{j.id} <StatusBadge status={j.status} /></span>
        <span className="tabular text-muted">{num(j.processed_items)} / {num(j.total_items ?? 0)} processed{j.failed_items ? `, ${j.failed_items} failed` : ""}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pctDone} aria-valuemin={0} aria-valuemax={100} aria-label="Processing progress">
        <div className="h-full bg-primary transition-all" style={{ width: `${pctDone}%` }} />
      </div>
      {j.status === "completed" && j.result && (
        <Notice tone="success" title="Processing complete">
          {num(j.result.processed)} records labelled{j.result.near_duplicates ? `, ${j.result.near_duplicates} near-duplicates flagged` : ""}.
          {j.result.clustering && <> Clustering: {j.result.clustering.status === "completed" ? `${j.result.clustering.clusters} clusters` : j.result.clustering.reason}</>}
        </Notice>
      )}
      {j.status === "failed" && <Notice tone="danger" title="Processing failed">{j.error}</Notice>}
    </div>
  );
}

function Importer({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview>();
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [role, setRole] = useState("query");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<{ dataset: Dataset; summary: { rows: number; stored: number; duplicates: number; rejected: number } }>();

  const pick = async (f: File | null) => {
    setFile(f); setPreview(undefined); setResult(undefined); setError(undefined);
    if (!f) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const p = await api.post<Preview>("/api/datasets/preview", fd);
      setPreview(p);
      setMapping(Object.fromEntries(Object.entries(p.mapping).filter(([, v]) => v).map(([k, v]) => [k, v as string])));
      setName(f.name.replace(/\.(csv|json)$/i, ""));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!file) return;
    setBusy(true); setError(undefined);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("mapping", JSON.stringify(mapping));
    fd.append("name", name);
    fd.append("default_role", role);
    fd.append("force", String(force));
    try {
      setResult(await api.post("/api/datasets/upload", fd));
      onImported();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 409 ? `${e.message} Tick "Import again anyway" to create a new version.` : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Field label="CSV or JSON file (max 20 MB)" htmlFor="file" hint="CSV needs a header row; JSON must be an array of objects (or {&quot;records&quot;: [...]}).">
        <Input id="file" type="file" accept=".csv,.json,text/csv,application/json" onChange={(e) => pick(e.target.files?.[0] ?? null)} className="h-auto py-1.5" />
      </Field>
      {busy && !preview && <LoadingBlock rows={2} />}
      {error && <Notice tone="danger">{error}</Notice>}
      {preview && !result && (
        <>
          <p className="text-sm text-muted">{num(preview.row_count)} rows · {preview.columns.length} columns detected. Check the column mapping — unmapped fields are left empty, never guessed.</p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {FIELDS.map(([key, title, hint]) => (
              <Field key={key} label={title} htmlFor={`map-${key}`} hint={hint || undefined}>
                <Select id={`map-${key}`} value={mapping[key] ?? ""} placeholder="— not mapped —"
                  onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))}
                  options={preview.columns.map((c) => ({ value: c, label: c }))} />
              </Field>
            ))}
          </div>
          <Card title="First rows" bodyClassName="p-0 px-4 pb-2">
            <Table caption="Preview of the first rows">
              <thead><tr>{preview.columns.slice(0, 8).map((c) => <Th key={c}>{c}</Th>)}</tr></thead>
              <tbody>{preview.sample.map((r, i) => (
                <tr key={i}>{preview.columns.slice(0, 8).map((c) => <Td key={c} className="max-w-[18rem] truncate text-xs">{r[c] ?? ""}</Td>)}</tr>
              ))}</tbody>
            </Table>
          </Card>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Dataset name" htmlFor="ds-name"><Input id="ds-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Default text type" htmlFor="ds-role" hint="Used when no text-type column is mapped. Gap detection applies to queries, questions, complaints and comments.">
              <Select id="ds-role" value={role} onChange={(e) => setRole(e.target.value)}
                options={["query", "question", "complaint", "discussion", "faq", "news", "article"].map((v) => ({ value: v, label: v }))} />
            </Field>
            <div className="flex items-end"><Checkbox label="Import again anyway (same file)" checked={force} onChange={(e) => setForce(e.target.checked)} /></div>
          </div>
          <Button variant="primary" onClick={submit} loading={busy} disabled={!mapping.text}><FileUp className="h-4 w-4" />Import and process</Button>
          {!mapping.text && <p className="text-xs text-danger">Map a column to “Text” to continue.</p>}
        </>
      )}
      {result && (
        <div className="space-y-3">
          <Notice tone="success" title={`Imported as ${result.dataset.version}`}>
            {num(result.summary.rows)} rows read · {num(result.summary.stored - result.summary.duplicates)} unique stored ·
            {" "}{num(result.summary.duplicates)} duplicates flagged · {num(result.summary.rejected)} rejected.
          </Notice>
          {result.dataset.job && <JobProgress jobId={result.dataset.job.id} onDone={onImported} />}
          <div className="flex gap-2">
            <Link className="text-sm text-primary hover:underline" href={`/dataset/explorer?dataset_version_id=${result.dataset.id}`}>View imported records</Link>
            <Link className="text-sm text-primary hover:underline" href="/dataset/analytics">Open analytics</Link>
          </div>
        </div>
      )}
    </div>
  );
}

export default function UploadPage() {
  const list = useApi<Dataset[]>("/api/datasets", { refreshMs: 10000 });
  const [reproc, setReproc] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const detail = useApi<{ rejections: { row: number | string; reason: string }[] }>(expanded ? `/api/datasets/${expanded}` : null);

  const reprocess = async (id: number) => {
    setReproc(id);
    try { await api.post(`/api/datasets/${id}/reprocess`); list.reload(); } finally { setReproc(null); }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Import datasets" description="Upload labelled or unlabelled public text. Rows are validated, normalized, PII-redacted and deduplicated, then processed by the same NLP pipeline used for live collection. Manual labels are kept as ground truth; model predictions are stored alongside." />
      <Card title="New import">
        <OperatorOnly fallback={<p className="text-sm text-muted">Operator access is required to import data. Use the <strong>Operator access</strong> button in the top bar.</p>}>
          <Importer onImported={list.reload} />
        </OperatorOnly>
      </Card>
      <Card title="Import history" bodyClassName="p-0 px-4 pb-2" actions={<Button size="sm" variant="ghost" onClick={list.reload}><RefreshCw className="h-3.5 w-3.5" />Refresh</Button>}>
        {list.error && <div className="py-3"><ErrorState error={list.error} onRetry={list.reload} /></div>}
        {!list.data ? <div className="py-4"><LoadingBlock /></div> : list.data.length === 0 ? <EmptyState title="No datasets imported yet" /> : (
          <Table caption="Imported datasets">
            <thead><tr><Th>Version</Th><Th>Name / file</Th><Th className="text-right">Rows</Th><Th className="text-right">Unique</Th><Th className="text-right">Dupes</Th><Th className="text-right">Rejected</Th><Th className="text-right">Processed</Th><Th>Status</Th><Th>Imported</Th><Th /></tr></thead>
            <tbody>{list.data.map((d) => (
              <React.Fragment key={d.id}>
                <tr>
                  <Td className="font-medium">{d.version}</Td>
                  <Td><span className="block">{d.name}</span><span className="text-xs text-subtle">{d.source_file}</span></Td>
                  <Td className="text-right tabular">{num(d.record_count)}</Td><Td className="text-right tabular">{num(d.valid_records)}</Td>
                  <Td className="text-right tabular">{num(d.duplicate_records)}</Td>
                  <Td className="text-right tabular">{d.rejected_records ? <button className="text-primary underline" onClick={() => setExpanded(expanded === d.id ? null : d.id)}>{num(d.rejected_records)}</button> : 0}</Td>
                  <Td className="text-right tabular">{num(d.processed_records)}</Td>
                  <Td><StatusBadge status={d.job && ["pending", "running"].includes(d.job.status) ? d.job.status : d.processing_status} /></Td>
                  <Td className="text-xs"><Timestamp value={d.created_at} /></Td>
                  <Td className="whitespace-nowrap text-right">
                    <Link className="mr-2 text-xs text-primary hover:underline" href={`/dataset/explorer?dataset_version_id=${d.id}`}>Records</Link>
                    <OperatorOnly fallback={null}><Button size="sm" variant="ghost" loading={reproc === d.id} onClick={() => reprocess(d.id)}>Reprocess</Button></OperatorOnly>
                  </Td>
                </tr>
                {expanded === d.id && (
                  <tr><Td colSpan={10} className="bg-surface-2/50">
                    <p className="mb-1 text-xs font-medium text-muted">Rejected rows</p>
                    <ul className="max-h-48 overflow-y-auto text-xs">{(detail.data?.rejections ?? []).map((r, i) => <li key={i}>Row {r.row}: {r.reason}</li>)}</ul>
                  </Td></tr>
                )}
              </React.Fragment>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
