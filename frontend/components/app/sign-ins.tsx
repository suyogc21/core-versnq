"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

const REASONS: Record<string, string> = {
  wrong_password: "Wrong password",
  wrong_code: "Wrong code",
  ip_not_allowed: "Address not allowed",
};

export function SignInTable({ rows, showPerson }: { rows: components["schemas"]["SignInOut"][]; showPerson: boolean }) {
  if (rows.length === 0) return <p className="text-muted-foreground">No sign-ins yet.</p>;
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            {showPerson && <TableHead>Who</TableHead>}
            <TableHead>Result</TableHead>
            <TableHead>From</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id}>
              <TableCell className="whitespace-nowrap">{new Date(r.created_at).toLocaleString()}</TableCell>
              {showPerson && <TableCell>{r.user_name ?? r.email}</TableCell>}
              <TableCell className={r.success ? "" : "text-destructive"}>{r.success ? "Signed in" : (REASONS[r.reason ?? ""] ?? "Failed")}</TableCell>
              <TableCell className="max-w-64 truncate text-muted-foreground" title={r.user_agent ?? ""}>
                {[r.ip, device(r.user_agent)].filter(Boolean).join(" · ")}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** A short name for a browser / device from its user agent. */
export function device(ua: string | null | undefined): string {
  if (!ua) return "";
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iPhone" : /Mac OS X/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : /Linux/.test(ua) ? "Linux" : "";
  const app = /VersnqCoreApp/.test(ua) ? "Versnq app" : /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "";
  return [app, os].filter(Boolean).join(" on ");
}


/** My account → Signed-in devices and my recent sign-ins (finishing plan, batch 1). */
export function MyDevices() {
  const [rows, setRows] = useState<components["schemas"]["SignedInDevice"][] | null>(null);
  const [history, setHistory] = useState<components["schemas"]["SignInOut"][] | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const load = async () => unwrap(await api.GET("/api/v1/me/devices"));
  useEffect(() => {
    load()
      .then(setRows)
      .catch(() => setRows([]));
  }, []);
  async function signOut(id: string) {
    try {
      unwrap(await api.POST("/api/v1/me/devices/{session_id}/sign-out", { params: { path: { session_id: id } } }));
      toast.success("That device is signed out.");
      setRows(await load());
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function toggleHistory() {
    if (!history) setHistory(unwrap(await api.GET("/api/v1/me/sign-ins")));
    setShowHistory(!showHistory);
  }
  return (
    <div className="space-y-3">
      {rows === null ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : (
        <ul className="divide-y rounded-md border">
          {rows.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
              <span className="font-medium">{device(d.user_agent) || "Unknown device"}</span>
              <span className="text-muted-foreground">
                {[d.ip, `active ${new Date(d.last_active_at).toLocaleString()}`].filter(Boolean).join(" · ")}
              </span>
              {d.this_device ? (
                <span className="ml-auto text-xs text-muted-foreground">This device</span>
              ) : (
                <Button size="sm" variant="ghost" className="ml-auto" onClick={() => signOut(d.id)}>
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="text-sm underline" onClick={toggleHistory}>
        {showHistory ? "Hide my sign-ins" : "Show my recent sign-ins"}
      </button>
      {showHistory && history && <SignInTable rows={history} showPerson={false} />}
    </div>
  );
}
