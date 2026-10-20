"use client";

import React, { useState } from "react";
import { RecordRow, RecordTable } from "@/components/RecordTable";
import { Button, Card, EmptyState, Field, Input, Notice, PageHeader, Segmented } from "@/components/ui";
import { api } from "@/lib/api";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<"all" | "dataset" | "live">("all");
  const [res, setRes] = useState<{ items: RecordRow[]; min_similarity: number; embedding_model: string }>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true); setError(undefined);
    try { setRes(await api.post("/api/search/semantic", { query, scope, k: 25 })); }
    catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-5">
      <PageHeader title="Semantic search" description="Finds records with similar meaning, not just matching words, using sentence embeddings of every processed record." />
      <Card>
        <form onSubmit={run} className="flex flex-wrap items-end gap-3">
          <Field label="Describe what you are looking for" htmlFor="q" className="min-w-[16rem] flex-1">
            <Input id="q" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. installment not received after e-KYC" />
          </Field>
          <Segmented label="Workspace" value={scope} onChange={setScope} options={[{ value: "all", label: "Both" }, { value: "dataset", label: "Dataset" }, { value: "live", label: "Live" }]} />
          <Button type="submit" variant="primary" loading={busy} disabled={query.trim().length < 3}>Search</Button>
        </form>
      </Card>
      {error && <Notice tone="danger">{error}</Notice>}
      {res && (
        <Card title={`${res.items.length} similar records`} description={`Cosine similarity ≥ ${res.min_similarity} · ${res.embedding_model}`}>
          {res.items.length ? <RecordTable rows={res.items} showSimilarity /> : <EmptyState title="Nothing similar enough">Try different wording, or search the other workspace.</EmptyState>}
        </Card>
      )}
    </div>
  );
}
