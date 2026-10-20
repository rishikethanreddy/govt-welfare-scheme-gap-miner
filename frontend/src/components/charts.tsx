"use client";

import Link from "next/link";
import React, { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Segmented, Table, Td, Th } from "@/components/ui";
import { label, num, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface BarItem {
  key: string;
  label: string;
  value: number;
  share?: number | null;
  href?: string;
  color?: string;
  note?: string;
}

/** Horizontal bars as a semantic list: readable by screen readers without a separate table. */
export function BarList({ items, emptyText = "No data for the current filters.", valueLabel = "records", max }: {
  items: BarItem[]; emptyText?: string; valueLabel?: string; max?: number;
}) {
  if (!items.length) return <p className="py-6 text-center text-sm text-muted">{emptyText}</p>;
  const top = max ?? Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="space-y-1.5">
      {items.map((i) => {
        const inner = (
          <>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-foreground">{i.label}</span>
              <span className="shrink-0 tabular text-muted">
                {num(i.value)}{i.share != null && <span className="ml-1.5 text-subtle">{pct(i.share)}</span>}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
              <div className="h-full rounded-full" style={{ width: `${(i.value / top) * 100}%`, background: i.color ?? "var(--chart-1)" }} />
            </div>
            {i.note && <p className="mt-0.5 text-[11px] text-subtle">{i.note}</p>}
          </>
        );
        return (
          <li key={i.key} aria-label={`${i.label}: ${i.value} ${valueLabel}`}>
            {i.href ? <Link href={i.href} className="block rounded px-1 py-0.5 hover:bg-surface-2">{inner}</Link> : <div className="px-1 py-0.5">{inner}</div>}
          </li>
        );
      })}
    </ul>
  );
}

export const GAP_COLORS: Record<string, string> = {
  yes: "var(--gap-yes)", no: "var(--gap-no)", unclear: "var(--gap-unclear)", not_applicable: "var(--gap-na)", unlabelled: "var(--border-strong)",
};

/** 100% stacked bar of gap outcomes with an explicit legend of counts. */
export function OutcomeBar({ counts }: { counts: Record<string, number> }) {
  const order = ["yes", "no", "unclear", "not_applicable", "unlabelled"];
  const total = order.reduce((s, k) => s + (counts[k] ?? 0), 0);
  if (!total) return <p className="text-sm text-muted">No records.</p>;
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2" role="img"
        aria-label={order.filter((k) => counts[k]).map((k) => `${label(k === "unlabelled" ? "Not processed" : k)} ${counts[k]}`).join(", ")}>
        {order.map((k) => counts[k] ? <div key={k} style={{ width: `${(counts[k] / total) * 100}%`, background: GAP_COLORS[k] }} /> : null)}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
        {order.map((k) => (
          <li key={k} className="flex items-center gap-1.5 whitespace-nowrap">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: GAP_COLORS[k] }} aria-hidden />
            <span className="text-muted">{k === "unlabelled" ? "Not processed" : label(k)}</span>
            <span className="tabular font-medium text-foreground">{num(counts[k] ?? 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Small inline gap-rate meter with the denominator shown, so small samples are visible. */
export function RateCell({ yes, no, minDecided = 5 }: { yes: number; no: number; minDecided?: number }) {
  const d = yes + no;
  if (!d) return <span className="text-subtle">—</span>;
  const rate = yes / d;
  return (
    <span className="flex items-center gap-2" title={`${yes} of ${d} decided records`}>
      <span className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <span className="block h-full rounded-full" style={{ width: `${rate * 100}%`, background: "var(--gap-yes)" }} />
      </span>
      <span className={cn("tabular", d < minDecided && "text-subtle")}>{pct(rate)}</span>
      <span className="text-[11px] text-subtle tabular">n={d}</span>
    </span>
  );
}

export function Timeline({ items, dateField, missing }: {
  items: { month: string; total: number; yes: number }[]; dateField: string; missing: number;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  if (!items.length) {
    return <p className="py-6 text-center text-sm text-muted">No dated records{missing ? ` (${num(missing)} records have no ${dateField === "published" ? "publication" : "collection"} date)` : ""}.</p>;
  }
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs text-muted">
          By {dateField === "published" ? "source publication month" : "collection month"}
          {missing > 0 && ` · ${num(missing)} records without a date are not shown`}
        </p>
        <Segmented label="Timeline view" value={view} onChange={setView}
          options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />
      </div>
      {view === "chart" ? (
        <div className="h-56" role="img" aria-label="Records and gap signals per month; switch to Table view for exact values">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={items} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis dataKey="month" tick={{ fontSize: 11, fill: "var(--muted)" }} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--muted)" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}
                cursor={{ fill: "var(--surface-2)" }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="total" name="Records" fill="var(--chart-1)" radius={[2, 2, 0, 0]} />
              <Bar dataKey="yes" name="Gap signals" fill="var(--gap-yes)" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <Table caption="Records per month">
          <thead><tr><Th>Month</Th><Th className="text-right">Records</Th><Th className="text-right">Gap signals</Th></tr></thead>
          <tbody>{items.map((i) => (
            <tr key={i.month}><Td>{i.month}</Td><Td className="text-right tabular">{num(i.total)}</Td><Td className="text-right tabular">{num(i.yes)}</Td></tr>
          ))}</tbody>
        </Table>
      )}
    </div>
  );
}
