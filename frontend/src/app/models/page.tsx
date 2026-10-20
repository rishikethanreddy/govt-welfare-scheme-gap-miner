"use client";

import React, { useState } from "react";
import { Badge, Card, ErrorState, KeyValue, LoadingBlock, Notice, PageHeader, Segmented, Table, Td, Th } from "@/components/ui";
import { label, num } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { cn } from "@/lib/utils";

type Task = "awareness_gap" | "intent" | "gap_type";
interface Metrics { n: number; accuracy: number; macro_precision?: number; macro_recall?: number; macro_f1: number; weighted_f1: number;
  per_class?: Record<string, { precision: number; recall: number; "f1-score": number; support: number }>;
  confusion_matrix?: { labels: string[]; matrix: number[][] } }
interface Report {
  task: string; labels: string[]; selected: string; uncertainty_threshold: number;
  class_distribution: Record<string, Record<string, number>>; training_records: Record<string, number>;
  validation_comparison: Record<string, Metrics>; test: Metrics; test_by_slice: Record<string, Metrics>; test_baseline: Metrics;
  test_uncertainty?: { threshold: number; coverage: number; accuracy_on_covered: number | null; unclear: number };
  grouped_cv: { folds: number; grouping: string; macro_f1_mean: number | null; macro_f1_std: number | null; accuracy_mean: number | null };
  errors: { text: string; true: string; pred: string }[];
}
interface Status { embedding_model: string; models: Record<string, { available: boolean; version: string | null; algorithm: string | null; uncertainty_threshold: number | null }> }

const f = (x: number | null | undefined) => (x == null ? "—" : x.toFixed(3));
const SLICE: Record<string, string> = { original_en: "Original English", translated_hi: "Hindi translations",
  translated_hi_latn: "Romanized-Hindi translations", live_ai: "Live comments (AI-annotated)" };

function Confusion({ cm }: { cm: { labels: string[]; matrix: number[][] } }) {
  const max = Math.max(1, ...cm.matrix.flat());
  return (
    <div className="scrollbar-thin overflow-x-auto">
      <table className="text-xs">
        <caption className="sr-only">Confusion matrix: rows are true labels, columns are predicted labels</caption>
        <thead><tr><th className="p-1 text-left text-muted">true ↓ / predicted →</th>{cm.labels.map((l) => <th key={l} scope="col" className="max-w-[5rem] p-1 text-left font-medium text-muted">{label(l)}</th>)}</tr></thead>
        <tbody>{cm.matrix.map((row, i) => (
          <tr key={cm.labels[i]}><th scope="row" className="p-1 text-left font-medium text-muted">{label(cm.labels[i])}</th>
            {row.map((v, j) => (
              <td key={j} className={cn("h-9 w-12 border border-border text-center tabular", i === j && v > 0 && "font-semibold")}
                style={{ background: v ? `color-mix(in oklab, ${i === j ? "var(--success)" : "var(--danger)"} ${Math.round(12 + (v / max) * 55)}%, var(--surface))` : undefined }}>{v}</td>
            ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function ModelsPage() {
  const [task, setTask] = useState<Task>("awareness_gap");
  const rep = useApi<Report>(`/api/models/evaluation/${task}`);
  const status = useApi<Status>("/api/models/status");
  const r = rep.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Models & evaluation"
        description="Held-out evaluation of the deployed classifiers, produced by the training script on the labelled dataset. Nothing here is estimated or hand-entered."
        actions={<Segmented label="Task" value={task} onChange={setTask} options={[{ value: "awareness_gap", label: "Awareness gap" }, { value: "intent", label: "Intent" }, { value: "gap_type", label: "Gap type" }]} />} />
      <Notice tone="info" title="About the evaluation data">
        Test records come from four slices: the original manually labelled English records, Hindi and romanized-Hindi
        translations of them (labels inherited, never shared between train and test), and real collected comments labelled by
        an AI assistant. Per-slice results are shown below; the grouped cross-validation is the more stable estimate.
      </Notice>
      {status.data && (
        <Card title="Deployed models">
          <Table caption="Deployed model versions"><thead><tr><Th>Task</Th><Th>Version</Th><Th>Algorithm</Th><Th>Uncertainty threshold</Th></tr></thead>
            <tbody>{Object.entries(status.data.models).map(([t, m]) => (
              <tr key={t}><Td>{label(t)}</Td><Td className="break-all font-mono text-xs">{m.version ?? <Badge tone="danger">not installed</Badge>}</Td><Td>{m.algorithm}</Td><Td className="tabular">{m.uncertainty_threshold || "—"}</Td></tr>
            ))}</tbody></Table>
          <p className="mt-2 text-xs text-muted">Embeddings: {status.data.embedding_model}. Scheme detection is rule-based (word-boundary alias matching) and therefore has no trained metrics.</p>
        </Card>
      )}
      {rep.error && <ErrorState error={rep.error} onRetry={rep.reload} />}
      {!r && !rep.error && <LoadingBlock rows={8} />}
      {r && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Test split (held out)" description={`Selected model: ${label(r.selected)}; refit on train+val, evaluated once.`}>
              <Table caption="Test metrics vs baseline">
                <thead><tr><Th>Model</Th><Th className="text-right">n</Th><Th className="text-right">Accuracy</Th><Th className="text-right">Macro-F1</Th><Th className="text-right">Weighted-F1</Th></tr></thead>
                <tbody>
                  <tr><Td>Majority-class baseline</Td><Td className="text-right tabular">{r.test_baseline.n}</Td><Td className="text-right tabular">{f(r.test_baseline.accuracy)}</Td><Td className="text-right tabular">{f(r.test_baseline.macro_f1)}</Td><Td className="text-right tabular">{f(r.test_baseline.weighted_f1)}</Td></tr>
                  <tr className="font-medium"><Td>{label(r.selected)}</Td><Td className="text-right tabular">{r.test.n}</Td><Td className="text-right tabular">{f(r.test.accuracy)}</Td><Td className="text-right tabular">{f(r.test.macro_f1)}</Td><Td className="text-right tabular">{f(r.test.weighted_f1)}</Td></tr>
                  {Object.entries(r.test_by_slice).map(([k, m]) => (
                    <tr key={k}><Td className="pl-5 text-muted">{SLICE[k] ?? k}</Td><Td className="text-right tabular">{m.n}</Td><Td className="text-right tabular">{f(m.accuracy)}</Td><Td className="text-right tabular">{f(m.macro_f1)}</Td><Td className="text-right tabular">{f(m.weighted_f1)}</Td></tr>
                  ))}
                </tbody>
              </Table>
              <KeyValue className="mt-4" items={[
                ["Macro precision / recall", `${f(r.test.macro_precision)} / ${f(r.test.macro_recall)}`],
                ["Grouped CV", `${r.grouped_cv.folds}-fold by ${r.grouped_cv.grouping}: macro-F1 ${f(r.grouped_cv.macro_f1_mean)} ± ${f(r.grouped_cv.macro_f1_std)}, accuracy ${f(r.grouped_cv.accuracy_mean)}`],
                ...(r.test_uncertainty ? [["Uncertainty band", `Below ${r.uncertainty_threshold} confidence the outcome is "unclear". On test: ${Math.round(r.test_uncertainty.coverage * 100)}% decided, accuracy on decided ${f(r.test_uncertainty.accuracy_on_covered)}.`] as [string, React.ReactNode]] : []),
                ["Training records", Object.entries(r.training_records).map(([k, v]) => `${SLICE[k] ?? k}: ${v}`).join(" · ")],
              ]} />
            </Card>
            <Card title="Model selection (validation split)" description="Candidates fitted on train, compared on validation by macro-F1.">
              <Table caption="Validation comparison">
                <thead><tr><Th>Candidate</Th><Th className="text-right">n</Th><Th className="text-right">Accuracy</Th><Th className="text-right">Macro-F1</Th></tr></thead>
                <tbody>{Object.entries(r.validation_comparison).map(([k, m]) => (
                  <tr key={k} className={k === r.selected ? "font-medium" : ""}><Td>{label(k)}{k === r.selected && <Badge tone="primary" className="ml-2">selected</Badge>}</Td><Td className="text-right tabular">{m.n}</Td><Td className="text-right tabular">{f(m.accuracy)}</Td><Td className="text-right tabular">{f(m.macro_f1)}</Td></tr>
                ))}</tbody>
              </Table>
              <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-subtle">Class distribution</h3>
              <Table caption="Class distribution by split">
                <thead><tr><Th>Class</Th>{["train", "val", "test"].map((s) => <Th key={s} className="text-right">{s}</Th>)}</tr></thead>
                <tbody>{r.labels.map((l) => (
                  <tr key={l}><Td>{label(l)}</Td>{["train", "val", "test"].map((s) => <Td key={s} className="text-right tabular">{num(r.class_distribution[s]?.[l] ?? 0)}</Td>)}</tr>
                ))}</tbody>
              </Table>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Per-class results (test)">
              <Table caption="Per-class precision, recall and F1">
                <thead><tr><Th>Class</Th><Th className="text-right">Precision</Th><Th className="text-right">Recall</Th><Th className="text-right">F1</Th><Th className="text-right">Support</Th></tr></thead>
                <tbody>{r.labels.map((l) => { const c = r.test.per_class?.[l]; return (
                  <tr key={l}><Td>{label(l)}</Td><Td className="text-right tabular">{f(c?.precision)}</Td><Td className="text-right tabular">{f(c?.recall)}</Td><Td className="text-right tabular">{f(c?.["f1-score"])}</Td><Td className="text-right tabular">{c?.support ?? 0}</Td></tr>
                ); })}</tbody>
              </Table>
            </Card>
            <Card title="Confusion matrix (test)">{r.test.confusion_matrix && <Confusion cm={r.test.confusion_matrix} />}</Card>
          </div>
          <Card title={`Misclassified test records (${r.errors.length})`} description="Inspecting errors is part of the evaluation; these are the actual test records the model got wrong.">
            {r.errors.length === 0 ? <p className="text-sm text-muted">None.</p> : (
              <ul className="divide-y divide-border">{r.errors.map((e, i) => (
                <li key={i} className="py-2 text-sm"><p>{e.text}</p><p className="mt-0.5 text-xs text-muted">true: <strong>{label(e.true)}</strong> · predicted: <strong>{label(e.pred)}</strong></p></li>
              ))}</ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
