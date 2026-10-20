"use client";

import Link from "next/link";
import React, { useState } from "react";
import { RateCell } from "@/components/charts";
import { FilterBar, Scope, useFilters } from "@/components/filters";
import { Region, TileMap } from "@/components/TileMap";
import { Card, EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Segmented, Stat, Table, Td, Th } from "@/components/ui";
import { qs } from "@/lib/api";
import { num, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Geo { regions: (Region & { public_voice: number; state?: string })[]; unknown_location: number; total_records: number; location_coverage: number | null; note: string }

const MIN_DECIDED = 5;

export default function GeographyView({ scope }: { scope: Scope }) {
  const filters = useFilters(scope);
  const [metric, setMetric] = useState<"records" | "gap_rate" | "yes">("records");
  const states = useApi<Geo>(`/api/analytics/geography${filters.query}`);
  const districts = useApi<Geo>(`/api/analytics/geography${qs({ ...filters.params, level: "district" })}`);
  const d = states.data;
  const explorer = (state: string) => `/${scope}/explorer${qs({ ...filters.values, state })}`;

  return (
    <div className="space-y-5">
      <PageHeader title="Geography"
        description="State and district come only from explicit source metadata (e.g. a dataset column or an official record). Locations are never inferred from names, language or the source's own location." />
      <FilterBar scope={scope} filters={filters} compact />
      {states.error && <ErrorState error={states.error} onRetry={states.reload} />}
      {states.loading && !d && <LoadingBlock rows={6} />}
      {d && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Records in scope" value={num(d.total_records)} />
            <Stat label="With a stated state" value={num(d.total_records - d.unknown_location)} sub={pct(d.location_coverage) + " coverage"} />
            <Stat label="Location not stated" value={num(d.unknown_location)} href={explorer("__unknown__")} sub="kept in all other analytics" />
            <Stat label="States / UTs represented" value={num(d.regions.length)} />
          </div>
          {d.regions.length === 0 ? (
            <Card><EmptyState title="No records with a stated location">
              {scope === "live"
                ? "Most public web sources do not state the asker's location, so live records usually have none. This is reported rather than guessed."
                : "The imported dataset has no state column, or it is empty for the current filters."}
            </EmptyState></Card>
          ) : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,34rem)_1fr]">
              <Card title="State tile map" actions={<Segmented label="Map metric" value={metric} onChange={setMetric}
                options={[{ value: "records", label: "Records" }, { value: "yes", label: "Gap signals" }, { value: "gap_rate", label: "Gap rate" }]} />}>
                <TileMap regions={d.regions} metric={metric} minDecided={MIN_DECIDED} hrefFor={explorer} />
                {metric === "gap_rate" && <p className="mt-2 text-xs text-muted">Rates are shown only where at least {MIN_DECIDED} records have a yes/no decision.</p>}
              </Card>
              <Card title="States" bodyClassName="p-0 px-4 pb-2" description="Accessible alternative to the map, with denominators.">
                <Table caption="Records and gap signals by state">
                  <thead><tr><Th>State</Th><Th className="text-right">Records</Th><Th className="text-right">Gap</Th><Th className="text-right">No gap</Th><Th className="text-right">Unclear</Th><Th>Gap rate</Th></tr></thead>
                  <tbody>{d.regions.map((r) => (
                    <tr key={r.value}>
                      <Td><Link className="hover:text-primary hover:underline" href={explorer(r.value)}>{r.value}</Link></Td>
                      <Td className="text-right tabular">{num(r.total)}</Td><Td className="text-right tabular">{num(r.yes)}</Td>
                      <Td className="text-right tabular">{num(r.no)}</Td><Td className="text-right tabular">{num(r.unclear)}</Td>
                      <Td><RateCell yes={r.yes} no={r.no} minDecided={MIN_DECIDED} /></Td>
                    </tr>
                  ))}</tbody>
                </Table>
              </Card>
            </div>
          )}
          {districts.data && districts.data.regions.length > 0 && (
            <Card title="Districts" description="Only where the source names the district explicitly." bodyClassName="p-0 px-4 pb-2">
              <Table caption="Records by district">
                <thead><tr><Th>District</Th><Th>State</Th><Th className="text-right">Records</Th><Th>Gap rate</Th></tr></thead>
                <tbody>{districts.data.regions.map((r) => (
                  <tr key={`${r.state}-${r.value}`}><Td>{r.value}</Td><Td className="text-muted">{r.state ?? "—"}</Td>
                    <Td className="text-right tabular">{num(r.total)}</Td><Td><RateCell yes={r.yes} no={r.no} minDecided={MIN_DECIDED} /></Td></tr>
                ))}</tbody>
              </Table>
            </Card>
          )}
          <Notice tone="info">Counts describe where analysed records come from. They are not measurements of awareness levels in those regions.</Notice>
        </>
      )}
    </div>
  );
}
