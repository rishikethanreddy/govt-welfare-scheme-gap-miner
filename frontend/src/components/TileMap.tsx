"use client";

import Link from "next/link";
import React from "react";
import { num, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Equal-area tile map of Indian states and union territories.
 * Each region is one tile at its approximate relative position, so small states
 * are as visible as large ones and no boundary geometry is required.
 */
const TILES: [string, string, number, number][] = [
  ["Jammu and Kashmir", "JK", 3, 0], ["Ladakh", "LA", 4, 0],
  ["Chandigarh", "CH", 1, 1], ["Punjab", "PB", 2, 1], ["Himachal Pradesh", "HP", 3, 1], ["Uttarakhand", "UK", 4, 1],
  ["Rajasthan", "RJ", 1, 2], ["Haryana", "HR", 2, 2], ["Delhi", "DL", 3, 2], ["Uttar Pradesh", "UP", 4, 2],
  ["Bihar", "BR", 5, 2], ["Sikkim", "SK", 6, 2], ["Arunachal Pradesh", "AR", 8, 2],
  ["Gujarat", "GJ", 1, 3], ["Madhya Pradesh", "MP", 2, 3], ["Chhattisgarh", "CG", 3, 3], ["Jharkhand", "JH", 4, 3],
  ["West Bengal", "WB", 5, 3], ["Assam", "AS", 6, 3], ["Nagaland", "NL", 7, 3],
  ["Dadra and Nagar Haveli and Daman and Diu", "DD", 0, 4], ["Maharashtra", "MH", 2, 4], ["Telangana", "TG", 3, 4],
  ["Odisha", "OD", 4, 4], ["Meghalaya", "ML", 6, 4], ["Manipur", "MN", 7, 4],
  ["Goa", "GA", 1, 5], ["Karnataka", "KA", 2, 5], ["Andhra Pradesh", "AP", 3, 5], ["Tripura", "TR", 6, 5], ["Mizoram", "MZ", 7, 5],
  ["Lakshadweep", "LD", 1, 6], ["Kerala", "KL", 2, 6], ["Tamil Nadu", "TN", 3, 6], ["Puducherry", "PY", 4, 6],
  ["Andaman and Nicobar Islands", "AN", 6, 6],
];

export interface Region { value: string; total: number; yes: number; no: number; unclear: number; gap_rate: number | null }

export function TileMap({ regions, metric, minDecided, hrefFor }: {
  regions: Region[]; metric: "records" | "gap_rate" | "yes"; minDecided: number; hrefFor?: (state: string) => string;
}) {
  const by = new Map(regions.map((r) => [r.value, r]));
  const max = Math.max(1, ...regions.map((r) => (metric === "records" ? r.total : r.yes)));
  const intensity = (r?: Region) => {
    if (!r) return null;
    if (metric === "gap_rate") return r.yes + r.no >= minDecided && r.gap_rate != null ? r.gap_rate : null;
    return (metric === "records" ? r.total : r.yes) / max;
  };
  const base = metric === "records" ? "var(--chart-1)" : "var(--gap-yes)";
  return (
    <div>
      <div className="grid grid-cols-9 gap-1" role="list" aria-label="States and union territories">
        {Array.from({ length: 7 * 9 }).map((_, idx) => {
          const col = idx % 9, row = Math.floor(idx / 9);
          const tile = TILES.find((t) => t[2] === col && t[3] === row);
          if (!tile) return <div key={idx} aria-hidden />;
          const [name, abbr] = tile;
          const r = by.get(name);
          const v = intensity(r);
          const insufficient = metric === "gap_rate" && r && v === null;
          const desc = r
            ? `${name}: ${r.total} records, ${r.yes} gap signals of ${r.yes + r.no} decided${insufficient ? " (too few decided records for a rate)" : ""}`
            : `${name}: no records`;
          const content = (
            <div title={desc}
              className={cn("flex aspect-square flex-col items-center justify-center rounded border text-[10px] font-semibold sm:text-xs",
                r ? "border-transparent text-foreground" : "border-dashed border-border text-subtle",
                insufficient && "bg-[repeating-linear-gradient(45deg,var(--surface-2),var(--surface-2)_4px,var(--surface)_4px,var(--surface)_8px)]")}
              style={v !== null && v !== undefined ? { background: `color-mix(in oklab, ${base} ${Math.round(15 + v * 70)}%, var(--surface))`, color: v > 0.55 ? "white" : undefined } : undefined}>
              <span>{abbr}</span>
              {r && <span className="font-normal tabular opacity-90">
                {metric === "records" ? num(r.total) : metric === "yes" ? num(r.yes) : v !== null ? pct(v) : "n<" + minDecided}
              </span>}
            </div>
          );
          return (
            <div key={idx} role="listitem" aria-label={desc}>
              {r && hrefFor ? <Link href={hrefFor(name)} className="block">{content}</Link> : content}
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm" style={{ background: `color-mix(in oklab, ${base} 20%, var(--surface))` }} />low</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm" style={{ background: `color-mix(in oklab, ${base} 85%, var(--surface))` }} />high</span>
        {metric === "gap_rate" && <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border border-border bg-[repeating-linear-gradient(45deg,var(--surface-2),var(--surface-2)_2px,var(--surface)_2px,var(--surface)_4px)]" />fewer than {minDecided} decided records</span>}
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border border-dashed border-border" />no records</span>
      </div>
    </div>
  );
}
