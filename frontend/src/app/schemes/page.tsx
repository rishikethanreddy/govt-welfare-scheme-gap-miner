"use client";

import Link from "next/link";
import React from "react";
import { RateCell } from "@/components/charts";
import { Badge, Card, LoadingBlock, PageHeader, Table, Td, Th } from "@/components/ui";
import { num } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Scheme { code: string; name: string; category: string; ministry: string; official_url: string; aliases: string[]; weak_aliases: string[] }
interface Row { value: string | null; total: number; yes: number; no: number; unclear: number }

export default function SchemesPage() {
  const reg = useApi<Scheme[]>("/api/schemes");
  const ds = useApi<Row[]>("/api/analytics/schemes?scope=dataset");
  const lv = useApi<Row[]>("/api/analytics/schemes?scope=live");
  const by = (rows: Row[] | undefined, code: string) => rows?.find((r) => r.value === code);
  return (
    <div className="space-y-5">
      <PageHeader title="Scheme registry" description="Schemes are detected with word-boundary alias matching. Strong aliases are unambiguous names; weak aliases (generic phrases) count only when no strong alias appears. Multi-scheme texts keep every match." />
      <Card bodyClassName="p-0 px-4 pb-2">
        {!reg.data ? <div className="py-4"><LoadingBlock rows={8} /></div> : (
          <Table caption="Schemes with records per workspace">
            <thead><tr><Th>Scheme</Th><Th>Aliases</Th><Th className="text-right">Dataset records</Th><Th>Dataset gap rate</Th><Th className="text-right">Live records</Th><Th>Live gap rate</Th></tr></thead>
            <tbody>{reg.data.map((s) => {
              const d = by(ds.data, s.code), l = by(lv.data, s.code);
              return (
                <tr key={s.code}>
                  <Td><Link className="font-medium hover:text-primary hover:underline" href={`/schemes/${encodeURIComponent(s.code)}`}>{s.code}</Link>
                    <span className="block text-xs text-muted">{s.name}</span><span className="text-[11px] text-subtle">{s.ministry}</span></Td>
                  <Td className="max-w-sm"><span className="flex flex-wrap gap-1">{s.aliases.slice(0, 6).map((a) => <Badge key={a}>{a}</Badge>)}
                    {s.weak_aliases.map((a) => <Badge key={a} tone="warning" title="weak alias">{a}</Badge>)}</span></Td>
                  <Td className="text-right tabular">{num(d?.total ?? 0)}</Td><Td>{d ? <RateCell yes={d.yes} no={d.no} /> : "—"}</Td>
                  <Td className="text-right tabular">{num(l?.total ?? 0)}</Td><Td>{l ? <RateCell yes={l.yes} no={l.no} /> : "—"}</Td>
                </tr>
              );
            })}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
