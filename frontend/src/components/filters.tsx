"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { RotateCcw, SlidersHorizontal } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Checkbox, Field, Input, Select } from "@/components/ui";
import { Params, qs } from "@/lib/api";
import { label } from "@/lib/format";
import { useApi } from "@/lib/hooks";

export type Scope = "dataset" | "live";

export const FILTER_KEYS = ["scheme", "state", "intent", "awareness_gap", "gap_type", "language", "text_role",
  "label_source", "source_id", "split", "needs_review", "date_field", "date_from", "date_to", "search",
  "include_duplicates", "include_synthetic", "min_confidence", "dataset_version_id", "campaign_id"] as const;

/** Filters live in the URL so every view is shareable and the same filters apply across pages. */
export function useFilters(scope: Scope) {
  const sp = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const values = useMemo(() => {
    const v: Record<string, string> = {};
    for (const k of FILTER_KEYS) {
      const x = sp.get(k);
      if (x) v[k] = x;
    }
    return v;
  }, [sp]);
  const params: Params = useMemo(() => ({ scope, ...values }), [scope, values]);
  const set = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    next.delete("page");
    router.replace(`${path}${next.toString() ? `?${next}` : ""}`, { scroll: false });
  }, [sp, router, path]);
  const reset = useCallback(() => router.replace(path, { scroll: false }), [router, path]);
  const active = Object.keys(values).length;
  return { values, params, query: qs(params), set, reset, active };
}

interface FilterOptions {
  schemes: string[]; states: string[]; intents: string[]; gap_types: string[]; languages: string[];
  text_roles: string[]; label_sources: string[]; splits: string[]; sources: { id: number; name: string }[];
}

export function FilterBar({ scope, filters, compact }: { scope: Scope; filters: ReturnType<typeof useFilters>; compact?: boolean }) {
  const { data: opts } = useApi<FilterOptions>(`/api/analytics/filters?scope=${scope}`);
  const { values, set, reset, active } = filters;
  const [search, setSearch] = useState(values.search ?? "");
  const [urlSearch, setUrlSearch] = useState(values.search);
  const [expanded, setExpanded] = useState(false);
  // Adopt external URL changes (e.g. "Reset") into the input during render.
  if (values.search !== urlSearch) {
    setUrlSearch(values.search);
    setSearch(values.search ?? "");
  }
  useEffect(() => {
    const t = setTimeout(() => { if ((values.search ?? "") !== search) set({ search }); }, 400);
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const o = (xs: string[] | undefined, fmt: (s: string) => string = (s) => label(s)) =>
    (xs ?? []).map((x) => ({ value: x, label: fmt(x) }));
  const sel = (key: string, title: string, options: { value: string; label: string }[], extra: { value: string; label: string }[] = []) => (
    <Field label={title} htmlFor={`f-${key}`} key={key}>
      <Select id={`f-${key}`} value={values[key] ?? ""} onChange={(e) => set({ [key]: e.target.value })}
        placeholder="All" options={[...extra, ...options]} />
    </Field>
  );

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <Field label="Search text" htmlFor="f-search" className="sm:col-span-2">
          <Input id="f-search" type="search" placeholder="Words in the record…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </Field>
        {sel("scheme", "Scheme", o(opts?.schemes, (s) => s), [{ value: "__unknown__", label: "Other / Unknown" }])}
        {sel("awareness_gap", "Gap outcome", ["yes", "no", "unclear", "not_applicable"].map((v) => ({ value: v, label: label(v) })))}
        {sel("intent", "Intent", o(opts?.intents))}
        {sel("gap_type", "Gap type", o(opts?.gap_types))}
      </div>
      {(expanded || !compact) && (
        <div className="mt-3 grid grid-cols-1 gap-3 border-t border-border pt-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          {sel("state", "State", o(opts?.states, (s) => s), [{ value: "__unknown__", label: "Location not stated" }])}
          {sel("language", "Language", o(opts?.languages))}
          {sel("text_role", "Text type", o(opts?.text_roles))}
          {sel("label_source", "Label source", o(opts?.label_sources))}
          {scope === "live"
            ? sel("source_id", "Source", (opts?.sources ?? []).map((s) => ({ value: String(s.id), label: s.name })))
            : sel("split", "Split", o(opts?.splits))}
          <Field label="Date basis" htmlFor="f-date_field">
            <Select id="f-date_field" value={values.date_field ?? "published"} onChange={(e) => set({ date_field: e.target.value === "published" ? null : e.target.value })}
              options={[{ value: "published", label: "Source publication date" }, { value: "collected", label: "Collection date" }]} />
          </Field>
          <Field label="From" htmlFor="f-from"><Input id="f-from" type="date" value={values.date_from?.slice(0, 10) ?? ""} onChange={(e) => set({ date_from: e.target.value || null })} /></Field>
          <Field label="To" htmlFor="f-to"><Input id="f-to" type="date" value={values.date_to?.slice(0, 10) ?? ""} onChange={(e) => set({ date_to: e.target.value ? `${e.target.value}T23:59:59` : null })} /></Field>
          <div className="flex flex-col justify-end gap-1.5 sm:col-span-2">
            <Checkbox label="Include synthetic records" checked={values.include_synthetic === "true"} onChange={(e) => set({ include_synthetic: e.target.checked ? "true" : null })} />
            <Checkbox label="Include duplicates" checked={values.include_duplicates === "true"} onChange={(e) => set({ include_duplicates: e.target.checked ? "true" : null })} />
          </div>
        </div>
      )}
      <div className="mt-3 flex items-center gap-2">
        {compact && (
          <Button size="sm" variant="ghost" onClick={() => setExpanded((x) => !x)} aria-expanded={expanded}>
            <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />{expanded ? "Fewer filters" : "More filters"}
          </Button>
        )}
        {active > 0 && (
          <Button size="sm" variant="ghost" onClick={reset}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Reset {active} filter{active > 1 ? "s" : ""}</Button>
        )}
      </div>
    </div>
  );
}
