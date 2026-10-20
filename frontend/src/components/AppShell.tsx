"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Activity, BarChart3, Boxes, Database, FlaskConical, Globe2, Home, Layers, ListTree,
  Map as MapIcon, Menu, Moon, Radio, Search, Sun, Table2, Upload, X,
} from "lucide-react";
import React, { useState } from "react";
import { OperatorButton } from "@/components/OperatorAccess";
import { useApi, useMounted } from "@/lib/hooks";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: React.ElementType; exact?: boolean };

const NAV: { heading: string; items: NavItem[] }[] = [
  { heading: "", items: [{ href: "/", label: "Overview", icon: Home, exact: true }] },
  {
    heading: "Dataset intelligence",
    items: [
      { href: "/dataset/analytics", label: "Analytics", icon: BarChart3 },
      { href: "/dataset/explorer", label: "Records", icon: Table2 },
      { href: "/dataset/clusters", label: "Semantic clusters", icon: Boxes },
      { href: "/dataset/geography", label: "Geography", icon: MapIcon },
      { href: "/dataset/upload", label: "Import & history", icon: Upload },
    ],
  },
  {
    heading: "Live collection",
    items: [
      { href: "/live", label: "Live monitor", icon: Radio, exact: true },
      { href: "/live/campaigns", label: "Collection jobs", icon: Activity },
      { href: "/live/sources", label: "Source registry", icon: Globe2 },
      { href: "/live/analytics", label: "Analytics", icon: BarChart3 },
      { href: "/live/explorer", label: "Records", icon: Table2 },
      { href: "/live/clusters", label: "Semantic clusters", icon: Boxes },
    ],
  },
  {
    heading: "Analysis",
    items: [
      { href: "/analyze", label: "Text analyzer", icon: FlaskConical },
      { href: "/search", label: "Semantic search", icon: Search },
      { href: "/schemes", label: "Schemes", icon: ListTree },
      { href: "/models", label: "Models & evaluation", icon: Layers },
    ],
  },
];

function isActive(path: string, item: NavItem) {
  return item.exact ? path === item.href : path === item.href || path.startsWith(item.href + "/");
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useMounted();
  const dark = mounted && resolvedTheme === "dark";
  return (
    <button onClick={() => setTheme(dark ? "light" : "dark")} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="rounded-md p-2 text-muted hover:bg-surface-2 hover:text-foreground">
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

function HealthDot() {
  const { data, error } = useApi<{ status: string; worker_alive: boolean; migrations?: { up_to_date: boolean } }>(
    "/api/health", { refreshMs: 30000 });
  const ok = data?.status === "healthy";
  const text = error ? "API unreachable" : !data ? "Checking…" : ok ? (data.worker_alive ? "All systems normal" : "Worker offline")
    : "Degraded";
  const color = error ? "bg-danger" : !data ? "bg-subtle" : ok && data.worker_alive ? "bg-success" : "bg-warning";
  return (
    <span role="status" className="flex items-center gap-2 rounded-md px-2 py-1 text-xs text-muted">
      <span className={cn("h-2 w-2 rounded-full", color)} aria-hidden />
      <span className="hidden sm:inline">{text}</span>
    </span>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="flex h-full flex-col">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-2.5 px-4 py-4">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Database className="h-4 w-4" aria-hidden />
        </span>
        <span className="leading-tight">
          <span className="block text-sm font-semibold text-foreground">Awareness Gap Miner</span>
          <span className="block text-[11px] text-muted">Welfare scheme text analytics</span>
        </span>
      </Link>
      <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-2 pb-6">
        {NAV.map((sec) => (
          <div key={sec.heading || "root"}>
            {sec.heading && <p className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-subtle">{sec.heading}</p>}
            <ul className="space-y-0.5">
              {sec.items.map((item) => {
                const active = isActive(path, item);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link href={item.href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                      className={cn("flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                        active ? "bg-primary-soft font-medium text-primary" : "text-muted hover:bg-surface-2 hover:text-foreground")}>
                      <Icon className="h-4 w-4 shrink-0" aria-hidden />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  // The drawer belongs to the page it was opened on, so navigating closes it.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === path;
  const setOpen = (v: boolean) => setOpenOn(v ? path : null);
  const workspace = path.startsWith("/dataset") ? "Dataset workspace" : path.startsWith("/live") ? "Live collection workspace" : null;

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only z-50 rounded bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r border-border bg-surface lg:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-border bg-surface shadow-xl">
            <button onClick={() => setOpen(false)} aria-label="Close navigation" className="absolute right-2 top-3 rounded p-2 text-muted hover:bg-surface-2">
              <X className="h-4 w-4" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-border bg-surface/90 px-3 backdrop-blur md:px-6">
          <button onClick={() => setOpen(true)} aria-label="Open navigation" className="rounded-md p-2 text-muted hover:bg-surface-2 lg:hidden">
            <Menu className="h-4 w-4" />
          </button>
          {workspace && (
            <span className={cn("rounded px-2 py-0.5 text-xs font-medium",
              path.startsWith("/live") ? "bg-info-soft text-info" : "bg-primary-soft text-primary")}>{workspace}</span>
          )}
          <div className="ml-auto flex items-center gap-1">
            <HealthDot />
            <OperatorButton />
            <ThemeToggle />
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-6">{children}</main>
        <footer className="border-t border-border px-6 py-3 text-xs text-subtle">
          Figures describe the analysed public text only and are not estimates of population-wide awareness.
        </footer>
      </div>
    </div>
  );
}
