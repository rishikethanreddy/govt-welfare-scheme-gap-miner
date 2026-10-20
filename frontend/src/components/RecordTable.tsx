"use client";

import Link from "next/link";
import { ArrowDown, ArrowUp } from "lucide-react";
import React from "react";
import { GapBadge, LabelSourceBadge, PublishedDate, SchemeTag } from "@/components/labels";
import { Badge, Table, Td, Th } from "@/components/ui";
import { label, truncate } from "@/lib/format";

export interface RecordRow {
  id: number; original_text: string; scheme_name: string | null; scheme_match_strength?: string | null;
  intent: string | null; intent_confidence?: number | null; awareness_gap: string | null; gap_confidence?: number | null;
  gap_type: string | null; label_source: string | null; needs_review?: boolean; language: string | null;
  text_role: string | null; state: string | null; source_name: string | null; source_url?: string | null;
  source_published_at: string | null; collected_at: string | null; is_duplicate?: boolean; is_synthetic?: boolean;
  similarity?: number;
}

export type Sort = { by: string; order: "asc" | "desc" };

function SortHeader({ col, children, sort, onSort, className }: {
  col: string; children: React.ReactNode; sort?: Sort; onSort?: (s: Sort) => void; className?: string;
}) {
  if (!onSort || !sort) return <Th className={className}>{children}</Th>;
  const active = sort.by === col;
  const next: Sort = { by: col, order: active && sort.order === "desc" ? "asc" : "desc" };
  return (
    <Th className={className} aria-sort={active ? (sort.order === "asc" ? "ascending" : "descending") : "none"}>
      <button onClick={() => onSort(next)} className="inline-flex items-center gap-1 hover:text-foreground">
        {children}
        {active && (sort.order === "asc" ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />)}
      </button>
    </Th>
  );
}

export function RecordTable({ rows, sort, onSort, showSimilarity, extra }: {
  rows: RecordRow[]; sort?: Sort; onSort?: (s: Sort) => void; showSimilarity?: boolean;
  extra?: (r: RecordRow) => React.ReactNode;
}) {
  return (
    <Table caption="Records">
      <thead>
        <tr>
          {showSimilarity && <Th className="w-16">Similarity</Th>}
          <Th className="min-w-[22rem]">Text</Th>
          <SortHeader col="scheme_name" sort={sort} onSort={onSort}>Scheme</SortHeader>
          <SortHeader col="awareness_gap" sort={sort} onSort={onSort}>Gap outcome</SortHeader>
          <SortHeader col="intent" sort={sort} onSort={onSort}>Intent</SortHeader>
          <SortHeader col="source_published_at" sort={sort} onSort={onSort}>Published</SortHeader>
          {extra && <Th />}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="hover:bg-surface-2/60">
            {showSimilarity && <Td className="tabular text-muted">{r.similarity?.toFixed(2)}</Td>}
            <Td>
              <Link href={`/records/${r.id}`} className="text-foreground hover:text-primary hover:underline">
                {truncate(r.original_text, 220)}
              </Link>
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-subtle">
                <Badge>{label(r.text_role)}</Badge>
                {r.language && <Badge>{label(r.language)}</Badge>}
                {r.state && <span>{r.state}</span>}
                {r.source_name && <span className="truncate">· {r.source_name}</span>}
                {r.is_duplicate && <Badge tone="warning">duplicate</Badge>}
                {r.is_synthetic && <Badge tone="warning">synthetic</Badge>}
              </div>
            </Td>
            <Td><SchemeTag value={r.scheme_name} strength={r.scheme_match_strength} /></Td>
            <Td>
              <div className="flex flex-col items-start gap-1">
                <GapBadge value={r.awareness_gap} confidence={r.label_source === "model" ? r.gap_confidence : undefined} />
                {r.gap_type && r.gap_type !== "none" && <span className="text-xs text-muted">{label(r.gap_type)}</span>}
                <LabelSourceBadge value={r.label_source} />
              </div>
            </Td>
            <Td className="text-sm">{label(r.intent)}</Td>
            <Td className="text-xs"><PublishedDate value={r.source_published_at} /></Td>
            {extra && <Td>{extra(r)}</Td>}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
