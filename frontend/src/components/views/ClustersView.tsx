"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Play } from "lucide-react";
import React, { useState } from "react";
import { Scope } from "@/components/filters";
import { GapBadge, PublishedDate } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { Badge, Button, Card, EmptyState, ErrorState, KeyValue, LoadingBlock, Notice, PageHeader, Pagination, Segmented } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, label, num, truncate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { cn } from "@/lib/utils";

interface ClusterItem {
  id: number; name: string; keywords: string[]; size: number; cohesion: number | null; persistence: number | null;
  low_cohesion: boolean; representative_texts: string[]; dominant_scheme: string | null; dominant_intent: string | null;
  dominant_gap_type: string | null; dominant_state: string | null; gap_signals: number; description: string | null;
}
interface Run { status: string; documents: number; clusters?: number; outliers?: number; min_cluster_size?: number;
  silhouette_cosine?: number | null; reason?: string; run_at: string; embedding_model: string; low_cohesion_clusters?: number }
interface Member { id: number; original_text: string; scheme_name: string | null; awareness_gap: string | null; gap_type: string | null;
  source_name: string | null; source_published_at: string | null; similarity: number; is_representative: boolean; language: string | null }

export default function ClustersView({ scope }: { scope: Scope }) {
  const sp = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const [sort, setSort] = useState<"size" | "gap_signals" | "cohesion">("gap_signals");
  const list = useApi<{ run: Run | null; items: ClusterItem[] }>(`/api/clusters?scope=${scope}&sort=${sort}`);
  const selected = Number(sp.get("cluster")) || list.data?.items[0]?.id;
  const [page, setPage] = useState(1);
  const detail = useApi<ClusterItem & { members: Member[]; total_members: number; total_pages: number; page: number }>(
    selected ? `/api/clusters/${selected}?page=${page}` : null);
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState<string>();
  const run = list.data?.run;

  const start = async () => {
    setRunning(true);
    setMsg(undefined);
    try {
      const j = await api.post<{ job_id: number }>(`/api/clusters/run?scope=${scope}`);
      setMsg(`Clustering job #${j.job_id} started. Results appear here when it finishes.`);
      setTimeout(list.reload, 4000);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Semantic clusters"
        description="Groups of semantically similar questions and comments (sentence embeddings → PCA → HDBSCAN). Outliers are not forced into clusters. Keywords are computed from member texts (c-TF-IDF)."
        actions={<OperatorOnly><Button size="sm" onClick={start} loading={running}><Play className="h-3.5 w-3.5" />Re-run clustering</Button></OperatorOnly>} />
      {msg && <Notice tone="info">{msg}</Notice>}
      {run && (
        <Card bodyClassName="p-3">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
            <span>Last run {dateTime(run.run_at)}</span>
            <span>{num(run.documents)} eligible records</span>
            {run.status === "completed" ? <>
              <span>{num(run.clusters)} clusters · {num(run.outliers)} outliers ({run.documents ? Math.round((run.outliers ?? 0) / run.documents * 100) : 0}%)</span>
              <span>Silhouette (cosine) {run.silhouette_cosine ?? "—"}</span>
              <span>min cluster size {run.min_cluster_size}</span>
            </> : <span className="text-warning">Skipped: {run.reason}</span>}
            <span>Embedding model {run.embedding_model}</span>
          </div>
        </Card>
      )}
      {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
      {list.loading && !list.data && <LoadingBlock rows={6} />}
      {list.data && list.data.items.length === 0 && (
        <Card><EmptyState title="No clusters for this workspace">
          {run?.reason ?? "Clustering runs automatically after processing once enough question-like records exist."}
        </EmptyState></Card>
      )}
      {list.data && list.data.items.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
          <Card title={`${list.data.items.length} clusters`} bodyClassName="p-2"
            actions={<Segmented label="Sort clusters" value={sort} onChange={setSort}
              options={[{ value: "gap_signals", label: "Gaps" }, { value: "size", label: "Size" }, { value: "cohesion", label: "Cohesion" }]} />}>
            <ul className="scrollbar-thin max-h-[70vh] space-y-1 overflow-y-auto">
              {list.data.items.map((c) => (
                <li key={c.id}>
                  <button onClick={() => { setPage(1); router.replace(`${path}?cluster=${c.id}`, { scroll: false }); }}
                    aria-current={c.id === selected}
                    className={cn("w-full rounded-md px-2.5 py-2 text-left transition-colors",
                      c.id === selected ? "bg-primary-soft" : "hover:bg-surface-2")}>
                    <span className="block truncate text-sm font-medium text-foreground">{c.name}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                      {num(c.size)} records · {c.dominant_scheme ?? "mixed"}
                      {c.gap_signals > 0 && <Badge tone="yes">{c.gap_signals} gaps</Badge>}
                      {c.low_cohesion && <Badge tone="warning">loose</Badge>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <div className="space-y-4">
            {detail.loading && !detail.data && <LoadingBlock rows={6} />}
            {detail.data && (
              <>
                <Card title={detail.data.name} description={detail.data.description ?? undefined}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <KeyValue items={[
                      ["Records", num(detail.data.size)],
                      ["Gap signals", num(detail.data.gap_signals)],
                      ["Cohesion", detail.data.cohesion?.toFixed(2) ?? "—"],
                      ["Stability", detail.data.persistence?.toFixed(2) ?? "—"],
                    ]} />
                    <KeyValue items={[
                      ["Dominant scheme", detail.data.dominant_scheme ?? "Mixed / unknown"],
                      ["Dominant intent", label(detail.data.dominant_intent)],
                      ["Dominant gap type", label(detail.data.dominant_gap_type)],
                      ["Keywords", <span key="k" className="flex flex-wrap gap-1">{detail.data.keywords.map((k) => <Badge key={k}>{k}</Badge>)}</span>],
                    ]} />
                  </div>
                  <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-subtle">Most central records</h3>
                  <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-sm text-foreground">
                    {detail.data.representative_texts.map((t, i) => <li key={i}>{truncate(t, 260)}</li>)}
                  </ol>
                </Card>
                <Card title={`Members (${num(detail.data.total_members)})`} description="Ordered by similarity to the cluster centre; each links to its full provenance.">
                  <ul className="divide-y divide-border">
                    {detail.data.members.map((m) => (
                      <li key={m.id} className="flex flex-col gap-1.5 py-2.5 sm:flex-row sm:items-start sm:justify-between">
                        <Link href={`/records/${m.id}`} className="min-w-0 text-sm text-foreground hover:text-primary hover:underline">
                          {truncate(m.original_text, 240)}
                        </Link>
                        <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs text-muted sm:flex-col sm:items-end">
                          <GapBadge value={m.awareness_gap} />
                          <span className="tabular">sim {m.similarity.toFixed(2)}</span>
                          <PublishedDate value={m.source_published_at} />
                        </div>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3"><Pagination page={detail.data.page} totalPages={detail.data.total_pages} onPage={setPage} /></div>
                </Card>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
