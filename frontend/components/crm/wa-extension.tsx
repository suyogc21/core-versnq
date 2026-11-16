"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { relative } from "@/lib/crm";

type Ext = components["schemas"]["ExtensionOut"];

function useRevoke() {
  const qc = useQueryClient();
  return async (e: Ext) => {
    if (!window.confirm(`Disconnect the extension${e.device ? ` on ${e.device}` : ""}? It stops logging at once.`)) return;
    try {
      unwrap(await api.POST("/api/v1/extensions/{ext_id}/revoke", { params: { path: { ext_id: e.id } } }));
      toast.success("Disconnected");
      await qc.invalidateQueries({ queryKey: ["extensions"] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
}

function Row({ e, showUser, onRevoke }: { e: Ext; showUser?: boolean; onRevoke: (e: Ext) => void }) {
  const live = !e.revoked_at;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm" data-extension-row={e.user_name}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {showUser && <span className="font-medium">{e.user_name}</span>}
          <span className="text-muted-foreground">{e.device || "Browser"}</span>
          <Badge variant={live ? "secondary" : "outline"}>{live ? "Connected" : "Disconnected"}</Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {e.last_used_at ? `Last active ${relative(e.last_used_at)}` : "Not used yet"}
          {e.version && ` · version ${e.version}`}
        </p>
      </div>
      {live && (
        <Button size="sm" variant="ghost" className="ms-auto" onClick={() => onRevoke(e)}>
          Disconnect
        </Button>
      )}
    </div>
  );
}

/** My account: connect the Versnq WhatsApp extension with a one-time code (step 10a). */
export function MyWhatsAppExtension() {
  const list = useQuery({ queryKey: ["extensions", "me"], queryFn: async () => unwrap(await api.GET("/api/v1/me/extensions")) });
  const revoke = useRevoke();
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null);
  const make = async () => {
    try {
      setCode(unwrap(await api.POST("/api/v1/me/extension/code")));
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const rows = list.data ?? [];
  return (
    <section className="space-y-3 border-b pb-8 last:border-0" data-wa-extension>
      <div>
        <h2 className="font-semibold">WhatsApp extension</h2>
        <p className="text-muted-foreground">
          Keep chatting from your own WhatsApp. With the Versnq extension in Chrome, WhatsApp Web shows the lead beside each chat, and your chats with leads are saved
          on their timeline. It never sends anything by itself, and chats with people who aren&apos;t leads stay on your computer.
        </p>
      </div>
      {code ? (
        <div className="space-y-1 rounded-md border p-3">
          <p className="text-sm">In the extension, enter your workspace address and this code:</p>
          <p className="font-mono text-2xl tracking-widest" data-connect-code>
            {code.code}
          </p>
          <p className="text-xs text-muted-foreground">Works once, for 10 minutes. Don&apos;t share it.</p>
        </div>
      ) : (
        <Button variant="outline" onClick={make}>
          Connect the extension
        </Button>
      )}
      {rows.length > 0 && (
        <div className="divide-y surface">
          {rows.map((e) => (
            <Row key={e.id} e={e} onRevoke={revoke} />
          ))}
        </div>
      )}
    </section>
  );
}

/** Settings → Connected inboxes: every rep's extension and when it last logged (step 10a). */
export function WhatsAppExtensionsAdmin() {
  const list = useQuery({ queryKey: ["extensions", "all"], queryFn: async () => unwrap(await api.GET("/api/v1/extensions")) });
  const revoke = useRevoke();
  const rows = list.data ?? [];
  return (
    <section className="space-y-3">
      <div>
        <h2 className="font-semibold">WhatsApp extension</h2>
        <p className="text-sm text-muted-foreground">
          Who logs their WhatsApp chats with leads through the Versnq extension. If someone&apos;s last activity is old while they still chat, the extension may need an
          update after a WhatsApp change.
        </p>
      </div>
      <div className="divide-y surface">
        {rows.length === 0 && <p className="p-4 text-sm text-muted-foreground">{list.isLoading ? "Loading…" : "Nobody has connected it yet."}</p>}
        {rows.map((e) => (
          <Row key={e.id} e={e} showUser onRevoke={revoke} />
        ))}
      </div>
    </section>
  );
}
