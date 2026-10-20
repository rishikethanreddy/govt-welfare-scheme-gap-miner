"use client";

import Link from "next/link";
import { AlertTriangle, Inbox, Loader2, RefreshCw, X } from "lucide-react";
import React, { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

// ── Layout ─────────────────────────────────────────────────────────────────

export function PageHeader({ title, description, actions, eyebrow }: {
  title: string; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 border-b border-border pb-5 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
        <h1 className="text-xl font-semibold tracking-tight text-foreground md:text-2xl">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, description, actions, children, className, bodyClassName, id }: {
  title?: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode;
  className?: string; bodyClassName?: string; id?: string;
}) {
  return (
    <section id={id} className={cn("min-w-0 rounded-lg border border-border bg-surface", className)}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-foreground">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function Grid({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("grid gap-4", className)}>{children}</div>;
}

// ── Controls ───────────────────────────────────────────────────────────────

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }: ButtonProps) {
  const styles = {
    primary: "bg-primary text-primary-foreground hover:bg-primary-hover border-transparent",
    secondary: "bg-surface text-foreground border-border-strong hover:bg-surface-2",
    ghost: "bg-transparent text-muted border-transparent hover:bg-surface-2 hover:text-foreground",
    danger: "bg-surface text-danger border-border-strong hover:bg-danger-soft",
  }[variant];
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        styles, className,
      )}
    >
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ href, children, variant = "secondary", className }: {
  href: string; children: React.ReactNode; variant?: "primary" | "secondary"; className?: string;
}) {
  return (
    <Link href={href} className={cn(
      "inline-flex h-9 items-center gap-1.5 rounded-md border px-3.5 text-sm font-medium transition-colors",
      variant === "primary" ? "border-transparent bg-primary text-primary-foreground hover:bg-primary-hover"
        : "border-border-strong bg-surface text-foreground hover:bg-surface-2", className)}>
      {children}
    </Link>
  );
}

export function Field({ label, htmlFor, hint, children, className }: {
  label: string; htmlFor?: string; hint?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">{label}</label>
      {children}
      {hint && <p className="text-xs text-subtle">{hint}</p>}
    </div>
  );
}

const controlCls = "h-9 w-full rounded-md border border-border-strong bg-surface px-2.5 text-sm text-foreground " +
  "placeholder:text-subtle focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(controlCls, props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(controlCls, "h-auto min-h-24 py-2 leading-relaxed", props.className)} />;
}

export function Select({ options, placeholder, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & {
  options: { value: string; label: string }[]; placeholder?: string;
}) {
  return (
    <select {...props} className={cn(controlCls, "pr-8", props.className)}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

export function Checkbox({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-foreground">
      <input type="checkbox" {...props} className="h-4 w-4 rounded border-border-strong accent-[var(--primary)]" />
      {label}
    </label>
  );
}

export function Segmented<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-border-strong bg-surface p-0.5">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn("rounded px-2.5 py-1 text-xs font-medium transition-colors",
            value === o.value ? "bg-primary-soft text-primary" : "text-muted hover:text-foreground")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ── Display ────────────────────────────────────────────────────────────────

export type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info" | "yes" | "no" | "unclear" | "na";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted border-border",
  primary: "bg-primary-soft text-primary border-transparent",
  success: "bg-success-soft text-success border-transparent",
  warning: "bg-warning-soft text-warning border-transparent",
  danger: "bg-danger-soft text-danger border-transparent",
  info: "bg-info-soft text-info border-transparent",
  yes: "bg-gap-yes-soft text-gap-yes border-transparent",
  no: "bg-gap-no-soft text-gap-no border-transparent",
  unclear: "bg-gap-unclear-soft text-gap-unclear border-transparent",
  na: "bg-gap-na-soft text-muted border-transparent",
};

export function Badge({ tone = "neutral", children, title, className }: {
  tone?: Tone; children: React.ReactNode; title?: string; className?: string;
}) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium leading-4", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, tone, href }: {
  label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "yes" | "unclear" | "primary"; href?: string;
}) {
  const color = tone === "yes" ? "text-gap-yes" : tone === "unclear" ? "text-gap-unclear" : tone === "primary" ? "text-primary" : "text-foreground";
  const body = (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface px-4 py-3">
      <span className="text-xs font-medium text-muted">{label}</span>
      <span className={cn("mt-1 text-2xl font-semibold tabular tracking-tight", color)}>{value}</span>
      {sub && <span className="mt-0.5 text-xs text-subtle">{sub}</span>}
    </div>
  );
  return href ? <Link href={href} className="block hover:opacity-90">{body}</Link> : body;
}

export function KeyValue({ items, className }: { items: [string, React.ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(0,9rem)_1fr] gap-x-4 gap-y-2 text-sm", className)}>
      {items.map(([k, v]) => (
        <React.Fragment key={k}>
          <dt className="text-muted">{k}</dt>
          <dd className="min-w-0 break-words text-foreground">{v}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-surface-2", className)} aria-hidden />;
}

export function LoadingBlock({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-5 w-full" />)}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <div className="text-subtle">{icon ?? <Inbox className="h-6 w-6" aria-hidden />}</div>
      <p className="text-sm font-medium text-foreground">{title}</p>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">Could not load this data</p>
        <p className="break-words text-xs opacity-90">{error.message}</p>
      </div>
      {onRetry && <Button size="sm" variant="secondary" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />Retry</Button>}
    </div>
  );
}

export function Notice({ tone = "info", children, title }: { tone?: "info" | "warning" | "success" | "danger"; children: React.ReactNode; title?: string }) {
  const map = { info: "border-info/30 bg-info-soft text-info", warning: "border-warning/30 bg-warning-soft text-warning",
    success: "border-success/30 bg-success-soft text-success", danger: "border-danger/30 bg-danger-soft text-danger" };
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("rounded-md border px-3 py-2.5 text-sm", map[tone])}>
      {title && <p className="font-medium">{title}</p>}
      <div className="text-[13px] leading-relaxed opacity-95">{children}</div>
    </div>
  );
}

export function Pagination({ page, totalPages, onPage, total }: { page: number; totalPages: number; onPage: (p: number) => void; total?: number }) {
  if (totalPages <= 1) return total !== undefined ? <p className="text-xs text-muted">{total} record{total === 1 ? "" : "s"}</p> : null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-xs text-muted">
      <span>Page {page} of {totalPages}{total !== undefined && ` · ${total.toLocaleString()} records`}</span>
      <div className="flex gap-1.5">
        <Button size="sm" onClick={() => onPage(1)} disabled={page <= 1}>First</Button>
        <Button size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>Previous</Button>
        <Button size="sm" onClick={() => onPage(page + 1)} disabled={page >= totalPages}>Next</Button>
      </div>
    </nav>
  );
}

export function Dialog({ open, onClose, title, children, footer }: {
  open: boolean; onClose: () => void; title: string; children: React.ReactNode; footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} onCancel={onClose}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-border bg-surface p-0 text-foreground shadow-xl backdrop:bg-black/40">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <button onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:bg-surface-2"><X className="h-4 w-4" /></button>
      </div>
      <div className="px-4 py-4">{children}</div>
      {footer && <div className="flex justify-end gap-2 border-t border-border px-4 py-3">{footer}</div>}
    </dialog>
  );
}

export function Table({ children, caption }: { children: React.ReactNode; caption?: string }) {
  return (
    <div className="scrollbar-thin -mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[40rem] border-collapse text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        {children}
      </table>
    </div>
  );
}

export function Th({ children, className, ...rest }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th {...rest} className={cn("border-b border-border px-2 py-2 text-left text-xs font-medium text-muted", className)}>{children}</th>;
}

export function Td({ children, className, ...rest }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...rest} className={cn("border-b border-border px-2 py-2 align-top", className)}>{children}</td>;
}
