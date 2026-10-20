"use client";

import React, { useState } from "react";
import { GapBadge } from "@/components/labels";
import { RecordRow, RecordTable } from "@/components/RecordTable";
import { Badge, Button, Card, Field, KeyValue, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { label } from "@/lib/format";

interface Alt { label: string; probability: number }
interface Result {
  normalized_text: string; text_role: string; nearest_labelled_similarity: number | null;
  language: { code: string; method: string; supported: boolean };
  scheme: { primary: string | null; schemes: string[]; strength: string | null; matches: { scheme: string; alias: string; strength: string }[] };
  intent: { label: string | null; confidence: number | null; status: string; alternatives: Alt[] };
  awareness_gap: { label: string | null; p_yes: number | null; confidence: number | null; status: string; reason: string };
  gap_type: { label: string | null; confidence: number | null; status: string; alternatives: Alt[] } | null;
  evidence: { text: string; intent: string; awareness_gap: string; gap_type: string; similarity: number }[];
  needs_review: boolean; model_versions: Record<string, string | null>;
  similar_records: { dataset: RecordRow[]; live: RecordRow[] };
}

const EXAMPLES = [
  "Am I eligible for PM-KISAN if the farmland is registered in my father's name?",
  "Someone told me Ujjwala gives a free gas cylinder every month for life, is that true?",
  "My 15th PM-KISAN installment was credited this week.",
  "Government approves 18.77 lakh houses under PMAY-U 2.0",
];

function Alts({ alts }: { alts: Alt[] }) {
  if (!alts?.length) return null;
  return <span className="text-xs text-muted">{alts.map((a) => `${label(a.label)} ${(a.probability * 100).toFixed(0)}%`).join(" · ")}</span>;
}

export default function AnalyzePage() {
  const [text, setText] = useState("");
  const [role, setRole] = useState("query");
  const [res, setRes] = useState<Result>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const run = async (t = text) => {
    setBusy(true); setError(undefined);
    try { setRes(await api.post<Result>("/api/analyze", { text: t, text_role: role })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Text analyzer" description="Runs the production pipeline (language detection, scheme detection, intent, awareness gap, gap type, similarity) on any text. Nothing is stored." />
      <Card>
        <div className="space-y-3">
          <Field label="Text" htmlFor="az-text"><Textarea id="az-text" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste a public question, complaint or comment…" maxLength={5000} /></Field>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Text type" htmlFor="az-role" className="w-56" hint="Gap detection applies to public-voice text only.">
              <Select id="az-role" value={role} onChange={(e) => setRole(e.target.value)}
                options={["query", "question", "complaint", "discussion", "faq", "news", "article"].map((v) => ({ value: v, label: label(v) }))} />
            </Field>
            <Button variant="primary" onClick={() => run()} loading={busy} disabled={text.trim().length < 5}>Analyze</Button>
          </div>
          <div className="flex flex-wrap gap-1.5 text-xs">
            <span className="text-muted">Examples:</span>
            {EXAMPLES.map((e) => <button key={e} className="rounded border border-border px-2 py-0.5 text-muted hover:bg-surface-2" onClick={() => { setText(e); run(e); }}>{e.slice(0, 48)}…</button>)}
          </div>
          {error && <Notice tone="danger">{error}</Notice>}
        </div>
      </Card>
      {res && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Awareness gap">
              <div className="flex items-center gap-2"><GapBadge value={res.awareness_gap.label} />
                {res.awareness_gap.p_yes != null && <span className="text-sm text-muted">P(gap) = {(res.awareness_gap.p_yes * 100).toFixed(0)}%</span>}
                {res.needs_review && <Badge tone="unclear">would go to review</Badge>}</div>
              <p className="mt-2 text-sm text-muted">{res.awareness_gap.reason}</p>
              {res.gap_type && <div className="mt-3 text-sm">Gap type: <strong>{label(res.gap_type.label)}</strong> {res.gap_type.confidence != null && `(${(res.gap_type.confidence * 100).toFixed(0)}%)`} <Alts alts={res.gap_type.alternatives} /></div>}
            </Card>
            <Card title="Other signals">
              <KeyValue items={[
                ["Scheme", res.scheme.primary ? <span key="s">{res.scheme.schemes.join(", ")} <Badge tone={res.scheme.strength === "weak" ? "warning" : "neutral"}>{res.scheme.strength} match</Badge></span> : "Other / Unknown"],
                ["Matched words", res.scheme.matches.map((m) => `"${m.alias}"`).join(", ") || "—"],
                ["Intent", <span key="i">{label(res.intent.label)} {res.intent.confidence != null && `(${(res.intent.confidence * 100).toFixed(0)}%)`} · {label(res.intent.status)}<br /><Alts alts={res.intent.alternatives} /></span>],
                ["Language", `${label(res.language.code)} (${res.language.method})${res.language.supported ? "" : " — not supported by the models"}`],
                ["Similarity to labelled data", res.nearest_labelled_similarity?.toFixed(2) ?? "—"],
              ]} />
            </Card>
          </div>
          <Card title="Nearest labelled examples" description="From the training data — use these to judge whether the prediction is plausible.">
            <ul className="space-y-2">{res.evidence.map((e, i) => (
              <li key={i} className="text-sm"><p>{e.text}</p><p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted"><GapBadge value={e.awareness_gap} />{label(e.gap_type)} · {label(e.intent)} · similarity {e.similarity.toFixed(2)}</p></li>
            ))}</ul>
          </Card>
          {(["dataset", "live"] as const).map((s) => (
            <Card key={s} title={`Similar records — ${s === "dataset" ? "dataset" : "live collection"}`}>
              {res.similar_records[s].length ? <RecordTable rows={res.similar_records[s]} showSimilarity /> : <p className="text-sm text-muted">No sufficiently similar records.</p>}
            </Card>
          ))}
          <p className="text-xs text-subtle">Models: {Object.entries(res.model_versions).map(([k, v]) => `${k} ${v ?? "—"}`).join(" · ")}</p>
        </>
      )}
    </div>
  );
}
