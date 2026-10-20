"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ExternalLink } from "lucide-react";
import React, { useState } from "react";
import { GapBadge, LabelSourceBadge, PublishedDate, SchemeTag, Timestamp } from "@/components/labels";
import { OperatorOnly } from "@/components/OperatorAccess";
import { RecordRow, RecordTable } from "@/components/RecordTable";
import { Badge, Button, Card, ErrorState, Field, KeyValue, LoadingBlock, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { label, num, timezoneName } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Evidence { text: string; intent: string; awareness_gap: string; gap_type: string; similarity: number }
interface Doc extends RecordRow {
  district: string | null; normalized_text: string; content_hash: string; origin: string; language_method: string | null; language_supported: boolean | null;
  schemes: string[] | null; scheme_context: string | null; predicted_intent: string | null; predicted_intent_confidence: number | null;
  predicted_gap: string | null; predicted_gap_confidence: number | null; predicted_gap_type: string | null; predicted_gap_type_confidence: number | null;
  gap_type_confidence: number | null; explanation: {
    gap_status?: string; gap_reason?: string; p_yes?: number | null; intent_status?: string;
    intent_alternatives?: { label: string; probability: number }[]; gap_type_alternatives?: { label: string; probability: number }[];
    scheme_matches?: { scheme: string; alias: string; strength: string }[]; evidence?: Evidence[];
  } | null;
  reviewed_at: string | null; reviewed_by: string | null; review_note: string | null; source_document_id: string | null;
  extraction_method: string | null; source_updated_at: string | null; first_seen_at: string | null; processed_at: string | null;
  created_at: string; pii_redacted: boolean; duplicate_of_id: number | null; near_duplicate_of_id: number | null;
  near_duplicate_similarity: number | null; confidence: string | null; notes: string | null; processing_status: string;
  processing_error: string | null; intent_model_version: string | null; gap_model_version: string | null;
  embedding_model_version: string | null; scheme_detection_version: string | null; split: string | null;
  campaign_id: number | null; dataset_version_id: number | null; crawl_page_id: number | null;
  source?: { id: number; name: string; url: string; type: string; policy_status: string };
  dataset?: { id: number; version: string; name: string };
  cluster?: { id: number; name: string; size: number; similarity: number } | null;
}

const GAP_TYPES = ["eligibility_gap", "application_gap", "documentation_gap", "benefit_gap", "payment_gap", "deadline_gap", "misconception"];
const INTENTS = ["eligibility", "application", "documentation", "benefits", "payment", "deadline", "complaint", "general_information"];

function ReviewForm({ doc, onSaved }: { doc: Doc; onSaved: () => void }) {
  const [gap, setGap] = useState(doc.awareness_gap ?? "");
  const [gapType, setGapType] = useState(doc.gap_type && doc.gap_type !== "none" ? doc.gap_type : "");
  const [intent, setIntent] = useState(doc.intent ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "success" | "danger"; text: string }>();
  const save = async () => {
    setSaving(true);
    setMsg(undefined);
    try {
      await api.patch(`/api/documents/${doc.id}/review`, {
        awareness_gap: gap || null, gap_type: gap === "yes" ? gapType || null : null, intent: intent || null, note: note || null,
      });
      setMsg({ tone: "success", text: "Review saved. The model prediction is kept alongside for comparison." });
      onSaved();
    } catch (e) {
      setMsg({ tone: "danger", text: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Gap outcome" htmlFor="rv-gap"><Select id="rv-gap" value={gap} onChange={(e) => setGap(e.target.value)}
          options={["yes", "no", "unclear", "not_applicable"].map((v) => ({ value: v, label: label(v) }))} /></Field>
        <Field label="Gap type" htmlFor="rv-type"><Select id="rv-type" value={gapType} onChange={(e) => setGapType(e.target.value)} disabled={gap !== "yes"}
          placeholder="—" options={GAP_TYPES.map((v) => ({ value: v, label: label(v) }))} /></Field>
        <Field label="Intent" htmlFor="rv-intent"><Select id="rv-intent" value={intent} onChange={(e) => setIntent(e.target.value)}
          placeholder="—" options={INTENTS.map((v) => ({ value: v, label: label(v) }))} /></Field>
      </div>
      <Field label="Reviewer note (optional)" htmlFor="rv-note"><Textarea id="rv-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} /></Field>
      {msg && <Notice tone={msg.tone}>{msg.text}</Notice>}
      <Button variant="primary" onClick={save} loading={saving} disabled={!gap}>Save correction</Button>
    </div>
  );
}

export default function RecordPage() {
  const { id } = useParams<{ id: string }>();
  const { data: d, error, loading, reload } = useApi<Doc>(`/api/documents/${id}`);
  const similar = useApi<{ items: RecordRow[]; note?: string }>(d ? `/api/documents/${id}/similar?k=8` : null);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !d) return <LoadingBlock rows={10} />;
  const ex = d.explanation ?? {};
  const workspace = d.origin === "dataset" ? "dataset" : "live";

  return (
    <div className="space-y-5">
      <PageHeader title={`Record #${d.id}`}
        eyebrow={<Link href={`/${workspace}/explorer`} className="text-xs text-primary hover:underline">← {workspace === "dataset" ? "Dataset records" : "Collected records"}</Link>}
        description={<span className="flex flex-wrap items-center gap-1.5">
          <Badge>{label(d.text_role)}</Badge><Badge>{label(d.language)}</Badge>
          {d.is_duplicate && <Badge tone="warning">duplicate of #{d.duplicate_of_id ?? d.near_duplicate_of_id}</Badge>}
          {d.is_synthetic && <Badge tone="warning">synthetic</Badge>}
          {d.pii_redacted && <Badge tone="info">personal identifiers redacted</Badge>}
        </span>} />

      <Card>
        <blockquote className="whitespace-pre-wrap text-[15px] leading-relaxed text-foreground">{d.original_text}</blockquote>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Classification" description="Effective labels used in analytics, and the model's own output.">
          <KeyValue items={[
            ["Scheme", <span key="s" className="flex flex-col gap-1"><SchemeTag value={d.scheme_name} strength={d.scheme_match_strength} />
              {d.schemes && d.schemes.length > 1 && <span className="text-xs text-muted">Also mentions: {d.schemes.slice(1).join(", ")}</span>}</span>],
            ["Gap outcome", <span key="g" className="flex flex-wrap items-center gap-1.5"><GapBadge value={d.awareness_gap} /><LabelSourceBadge value={d.label_source} /></span>],
            ["Gap type", label(d.gap_type)],
            ["Intent", label(d.intent)],
            ["Model prediction", <span key="p" className="text-sm">
              {label(d.predicted_gap, "—")}{d.predicted_gap_confidence != null && ` (${(d.predicted_gap_confidence * 100).toFixed(0)}%)`}
              {d.predicted_gap_type && ` · ${label(d.predicted_gap_type)}`}{d.predicted_intent && ` · intent ${label(d.predicted_intent)}`}
            </span>],
            ...(d.reviewed_at ? [["Reviewed", <span key="r"><Timestamp value={d.reviewed_at} />{d.review_note && ` — ${d.review_note}`}</span>] as [string, React.ReactNode]] : []),
            ...(d.confidence ? [["Annotator confidence", d.confidence] as [string, React.ReactNode]] : []),
          ]} />
          {ex.gap_reason && <Notice tone={ex.gap_status === "predicted" ? "info" : "warning"} title="Why this outcome"><p>{ex.gap_reason}</p>
            {ex.p_yes != null && <p className="mt-1">Model probability of a gap: {(ex.p_yes * 100).toFixed(0)}%.</p>}</Notice>}
          {ex.intent_alternatives && ex.intent_alternatives.length > 0 && (
            <p className="mt-3 text-xs text-muted">Intent alternatives: {ex.intent_alternatives.map((a) => `${label(a.label)} ${(a.probability * 100).toFixed(0)}%`).join(" · ")}</p>
          )}
        </Card>

        <Card title="Provenance & timestamps" description={`Times shown in your timezone (${timezoneName()}).`}>
          <KeyValue items={[
            ["Source", d.source ? <span key="src">{d.source.name} <Badge>{d.source.type}</Badge></span> : d.source_name ?? "—"],
            ["Source URL", d.source_url ? <a key="u" href={d.source_url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 break-all text-primary hover:underline">{d.source_url}<ExternalLink className="h-3 w-3 shrink-0" /></a> : "—"],
            ["Published by source", <PublishedDate key="p" value={d.source_published_at} />],
            ["Updated by source", d.source_updated_at ? <Timestamp key="u2" value={d.source_updated_at} /> : <span key="u2" className="text-subtle">Not stated</span>],
            ["First seen", <Timestamp key="f" value={d.first_seen_at} />],
            ["Collected", <Timestamp key="c" value={d.collected_at} />],
            ["Processed", <Timestamp key="pr" value={d.processed_at} />],
            ["Extraction", d.extraction_method ?? "—"],
            ...(d.dataset ? [["Dataset", `${d.dataset.name} (${d.dataset.version})${d.split ? ` · ${d.split} split` : ""}`] as [string, React.ReactNode]] : []),
            ...(d.campaign_id ? [["Collection job", <Link key="cj" className="text-primary hover:underline" href={`/live/campaigns/${d.campaign_id}`}>#{d.campaign_id}</Link>] as [string, React.ReactNode]] : []),
            ["Location", d.state ? `${d.district ? `${d.district}, ` : ""}${d.state}` : <span key="l" className="text-subtle">Not stated by source</span>],
          ]} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Nearest labelled examples" description="Most similar records from the labelled training data; useful for judging the prediction.">
          {ex.evidence && ex.evidence.length ? (
            <ul className="space-y-2.5">{ex.evidence.map((e, i) => (
              <li key={i} className="text-sm">
                <p className="text-foreground">{e.text}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <GapBadge value={e.awareness_gap} /> {label(e.gap_type)} · {label(e.intent)} · similarity {e.similarity.toFixed(2)}
                </p>
              </li>))}</ul>
          ) : <p className="text-sm text-muted">No evidence recorded (record not processed yet).</p>}
        </Card>
        <Card title="Correct labels" description="Optional: overwrite the model's labels for this record. Corrections are kept when records are reprocessed.">
          <OperatorOnly fallback={<p className="text-sm text-muted">Operator access is required to correct labels.</p>}>
            <ReviewForm doc={d} onSaved={reload} />
          </OperatorOnly>
        </Card>
      </div>

      <Card title="Similar records" description={d.cluster ? <>Member of cluster <Link className="text-primary hover:underline" href={`/${workspace}/clusters?cluster=${d.cluster.id}`}>{d.cluster.name}</Link> ({num(d.cluster.size)} records)</> : "Semantic neighbours in the same workspace."}>
        {!similar.data ? <LoadingBlock /> : similar.data.items.length === 0
          ? <p className="text-sm text-muted">{similar.data.note ?? "No sufficiently similar records."}</p>
          : <RecordTable rows={similar.data.items} showSimilarity />}
      </Card>

      <Card title="Technical details">
        <KeyValue items={[
          ["Content hash", <code key="h" className="break-all text-xs">{d.content_hash}</code>],
          ["Language detection", `${label(d.language)} via ${d.language_method ?? "—"}${d.language_supported === false ? " (not supported by the models)" : ""}`],
          ["Scheme matches", ex.scheme_matches?.length ? ex.scheme_matches.map((m) => `${m.scheme} ← "${m.alias}" (${m.strength})`).join("; ") : d.scheme_context ? `none in text; page context ${d.scheme_context}` : "none"],
          ["Model versions", <span key="mv" className="break-all text-xs">{[d.gap_model_version, d.intent_model_version, d.embedding_model_version, d.scheme_detection_version].filter(Boolean).join(" · ") || "—"}</span>],
          ["Processing", `${d.processing_status}${d.processing_error ? ` — ${d.processing_error}` : ""}`],
          ...(d.notes ? [["Notes", d.notes] as [string, React.ReactNode]] : []),
        ]} />
      </Card>
    </div>
  );
}
