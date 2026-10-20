"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

export interface LiveEvent { id: number; kind: string; level: string; message: string; url: string | null; source_id: number | null; document_id: number | null; created_at: string }
export interface LiveRecord { id: number; text: string; scheme: string | null; text_role: string | null; intent: string | null; awareness_gap: string | null;
  gap_type: string | null; language: string | null; source_name: string | null; source_url: string | null; source_published_at: string | null;
  collected_at: string | null; processed_at: string | null; campaign_id: number | null }
export interface CampaignSnapshot { id: number; name: string; status: string; stage: string | null; metrics: Record<string, number>;
  crawl_started_at: string | null; crawl_finished_at: string | null; elapsed_seconds: number | null; heartbeat_at: string | null; error_message: string | null }
export interface WorkerStatus { worker_alive: boolean; last_heartbeat: string | null; autopilot_enabled: boolean;
  worker_info: { state?: string; campaign_id?: number } | null; active_campaigns: CampaignSnapshot[] }

/**
 * Subscribes to the backend's Server-Sent Events stream. Everything shown comes
 * from rows the worker actually persisted; nothing is simulated client-side.
 * The server recycles connections periodically; we reconnect from the last ids seen.
 */
export function useLiveStream(path: string, opts: { initialRecords?: boolean } = {}) {
  const [status, setStatus] = useState<WorkerStatus>();
  const [campaign, setCampaign] = useState<CampaignSnapshot | null>();
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [records, setRecords] = useState<LiveRecord[]>([]);
  const [connected, setConnected] = useState(false);
  const [ended, setEnded] = useState(false);
  const cursor = useRef({ event: 0, record: opts.initialRecords ? 0 : -1 });

  useEffect(() => {
    let es: EventSource | null = null;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout>;

    const open = () => {
      const c = cursor.current;
      const sep = path.includes("?") ? "&" : "?";
      es = new EventSource(`${API_BASE}${path}${sep}after_event=${c.event}&after_record=${Math.max(c.record, 0)}`);
      es.onopen = () => setConnected(true);
      es.addEventListener("status", (e) => setStatus(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("campaign", (e) => setCampaign(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("log", (e) => {
        const ev: LiveEvent = JSON.parse((e as MessageEvent).data);
        cursor.current.event = Math.max(cursor.current.event, ev.id);
        setEvents((xs) => [ev, ...xs].slice(0, 300));
      });
      es.addEventListener("record", (e) => {
        const r: LiveRecord = JSON.parse((e as MessageEvent).data);
        cursor.current.record = Math.max(cursor.current.record, r.id);
        setRecords((xs) => (xs.some((x) => x.id === r.id) ? xs : [r, ...xs].slice(0, 100)));
      });
      es.addEventListener("end", () => { setEnded(true); es?.close(); setConnected(false); });
      es.addEventListener("reconnect", () => { es?.close(); if (!stopped) open(); });
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!stopped) retry = setTimeout(open, 3000);
      };
    };
    open();
    return () => { stopped = true; clearTimeout(retry); es?.close(); };
  }, [path]);

  return { status, campaign, events, records, connected, ended };
}
