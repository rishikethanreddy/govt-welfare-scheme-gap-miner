"use client";

import { KeyRound, LockOpen } from "lucide-react";
import React, { createContext, useCallback, useContext, useState } from "react";
import { Button, Dialog, Field, Input, Notice } from "@/components/ui";
import { api, ApiError, setOperatorKey } from "@/lib/api";
import { useOperatorKeyPresent } from "@/lib/hooks";

interface Ctx {
  isOperator: boolean;
  requestAccess: () => void;
  signOut: () => void;
}

const OperatorCtx = createContext<Ctx>({ isOperator: false, requestAccess: () => {}, signOut: () => {} });

export function useOperator() {
  return useContext(OperatorCtx);
}

export function OperatorProvider({ children }: { children: React.ReactNode }) {
  const isOperator = useOperatorKeyPresent();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [error, setError] = useState<string>();
  const [checking, setChecking] = useState(false);

  const submit = useCallback(async (e?: React.FormEvent) => {
    e?.preventDefault();
    setChecking(true);
    setError(undefined);
    setOperatorKey(key.trim());
    try {
      await api.get("/api/auth/check");
      setOpen(false);
      setKey("");
    } catch (err) {
      setOperatorKey(null);
      setError(err instanceof ApiError && err.status === 503
        ? "Operator actions are disabled on this server (ADMIN_API_KEY is not configured)."
        : err instanceof ApiError && err.status === 401 ? "That key was not accepted." : (err as Error).message);
    } finally {
      setChecking(false);
    }
  }, [key]);

  return (
    <OperatorCtx.Provider value={{ isOperator, requestAccess: () => setOpen(true), signOut: () => setOperatorKey(null) }}>
      {children}
      <Dialog open={open} onClose={() => setOpen(false)} title="Operator access"
        footer={<>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => submit()} loading={checking} disabled={!key.trim()}>Unlock</Button>
        </>}>
        <form onSubmit={submit} className="space-y-3">
          <p className="text-sm text-muted">
            Uploading data, running collection, editing sources and reviewing labels require the operator API key
            configured on the server (<code className="text-xs">ADMIN_API_KEY</code>). The key is kept only for this
            browser session.
          </p>
          <Field label="API key" htmlFor="operator-key">
            <Input id="operator-key" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} autoFocus />
          </Field>
          {error && <Notice tone="danger">{error}</Notice>}
        </form>
      </Dialog>
    </OperatorCtx.Provider>
  );
}

export function OperatorButton() {
  const { isOperator, requestAccess, signOut } = useOperator();
  return isOperator ? (
    <Button size="sm" variant="ghost" onClick={signOut} title="End operator session">
      <LockOpen className="h-3.5 w-3.5 text-success" aria-hidden /> Operator
    </Button>
  ) : (
    <Button size="sm" variant="ghost" onClick={requestAccess}>
      <KeyRound className="h-3.5 w-3.5" aria-hidden /> Operator access
    </Button>
  );
}

/** Wraps an operator-only control; shows an unlock prompt instead when locked. */
export function OperatorOnly({ children, fallback }: { children: React.ReactNode; fallback?: React.ReactNode }) {
  const { isOperator, requestAccess } = useOperator();
  if (isOperator) return <>{children}</>;
  return <>{fallback ?? (
    <Button size="sm" onClick={requestAccess}><KeyRound className="h-3.5 w-3.5" aria-hidden />Unlock to use</Button>
  )}</>;
}
