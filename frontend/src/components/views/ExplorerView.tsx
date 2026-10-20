"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Download } from "lucide-react";
import React from "react";
import { FilterBar, Scope, useFilters } from "@/components/filters";
import { RecordRow, RecordTable, Sort } from "@/components/RecordTable";
import { Card, EmptyState, ErrorState, LoadingBlock, PageHeader, Pagination, Select } from "@/components/ui";
import { downloadUrl, qs } from "@/lib/api";
import { num } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Page { items: RecordRow[]; total: number; page: number; total_pages: number }

export default function ExplorerView({ scope }: { scope: Scope }) {
  const filters = useFilters(scope);
  const sp = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const page = Number(sp.get("page") ?? 1);
  const pageSize = Number(sp.get("page_size") ?? 25);
  const sort: Sort = { by: sp.get("sort_by") ?? "id", order: (sp.get("sort_order") as "asc" | "desc") ?? "desc" };
  const setParam = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp.toString());
    Object.entries(patch).forEach(([k, v]) => next.set(k, v));
    router.replace(`${path}?${next}`, { scroll: false });
  };
  const { data, error, loading, reload } = useApi<Page>(
    `/api/documents${qs({ ...filters.params, page, page_size: pageSize, sort_by: sort.by, sort_order: sort.order })}`);
  const exportBtn = (fmt: string) => (
    <a href={downloadUrl("/api/documents/export", { ...filters.params, fmt })}
      className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2.5 text-xs font-medium hover:bg-surface-2">
      <Download className="h-3.5 w-3.5" aria-hidden />{fmt.toUpperCase()}
    </a>
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title={scope === "dataset" ? "Dataset records" : "Collected records"}
        description="Every record with its labels, provenance and timestamps. Exports contain exactly the records matched by the current filters."
        actions={<>{exportBtn("csv")}{exportBtn("json")}</>}
      />
      <FilterBar scope={scope} filters={filters} compact />
      <Card bodyClassName="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span aria-live="polite">{data ? `${num(data.total)} matching records` : "Loading…"}</span>
          <label className="flex items-center gap-2">Rows per page
            <Select aria-label="Rows per page" className="h-8 w-20" value={String(pageSize)}
              onChange={(e) => setParam({ page_size: e.target.value, page: "1" })}
              options={["25", "50", "100"].map((v) => ({ value: v, label: v }))} />
          </label>
        </div>
        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !data && <LoadingBlock rows={8} />}
        {data && data.items.length === 0 && <EmptyState title="No records match these filters" />}
        {data && data.items.length > 0 && (
          <>
            <RecordTable rows={data.items} sort={sort} onSort={(s) => setParam({ sort_by: s.by, sort_order: s.order, page: "1" })} />
            <Pagination page={data.page} totalPages={data.total_pages} total={data.total} onPage={(p) => setParam({ page: String(p) })} />
          </>
        )}
      </Card>
    </div>
  );
}
