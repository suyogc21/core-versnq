"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** What the Versnq Android app's phone part reports (mobile/…/PhonePlugin.java). */
type PhoneStatus = {
  installId: string;
  device: string;
  version: string;
  permission: boolean;
  connected: boolean;
  lastSyncAt?: number;
  lastError?: string | null;
  sent?: number;
};
type VersnqPhone = {
  info(): Promise<PhoneStatus>;
  requestCallPermission(): Promise<PhoneStatus>;
  connect(o: { token: string }): Promise<PhoneStatus>;
  disconnect(): Promise<PhoneStatus>;
  syncNow(): Promise<PhoneStatus>;
};

/** The phone part, present only when Core is open inside the Versnq Android app. */
export function phoneApp(): VersnqPhone | null {
  if (typeof window === "undefined") return null;
  const plugins = (window as unknown as { Capacitor?: { Plugins?: { VersnqPhone?: VersnqPhone } } }).Capacitor?.Plugins;
  return plugins?.VersnqPhone ?? null;
}

const ERRORS: Record<string, string> = {
  offline: "Couldn't reach Core: the calls will be sent when the internet is back.",
  signed_out: "This phone was removed in Core. Turn call tracking on again.",
  no_permission: "The app isn't allowed to read the call log. Allow it below.",
};

/** My account → Call tracking (calls plan C4.2), only inside the Android app: the rep allows the
 * call log once and connects this phone; from then on every call is sent to Core, even with the
 * app closed. Core keeps only calls with a lead's number. */
export function PhoneAppCallTracking() {
  const [phone] = useState(phoneApp);
  const [status, setStatus] = useState<PhoneStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    phone?.info().then(setStatus).catch(() => {});
  }, [phone]);

  if (!phone) return null;
  if (!status) return <p className="text-muted-foreground">Checking this phone…</p>;

  async function run(action: () => Promise<PhoneStatus>, ok?: string) {
    setBusy(true);
    try {
      setStatus(await action());
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const turnOn = () =>
    run(async () => {
      const s = await phone!.info();
      const out = unwrap(await api.POST("/api/v1/phone/devices", { body: { install_id: s.installId, device: s.device, version: s.version } }));
      return phone!.connect({ token: out.token });
    }, "Call tracking is on. Calls you make or get from now on go to the lead.");

  const turnOff = () =>
    run(async () => {
      const mine = unwrap(await api.GET("/api/v1/phone/devices"));
      for (const d of mine) if (d.device === status.device) unwrap(await api.POST("/api/v1/phone/devices/{device_id}/remove", { params: { path: { device_id: d.id } } }));
      return phone!.disconnect();
    }, "Call tracking is off on this phone");

  if (!status.permission)
    return (
      <div className="space-y-2">
        <p className="text-muted-foreground">To put your calls on the lead, allow the app to read this phone&apos;s call log. Only calls with a lead&apos;s number are kept in Core.</p>
        <Button disabled={busy} onClick={() => run(() => phone.requestCallPermission())}>
          Allow call log
        </Button>
      </div>
    );
  if (!status.connected)
    return (
      <Button disabled={busy} onClick={turnOn}>
        Turn on call tracking
      </Button>
    );
  return (
    <div className="space-y-2">
      <p>
        <span className="font-medium text-emerald-600">On</span> · {status.device}
        {status.lastSyncAt ? ` · last checked ${new Date(status.lastSyncAt).toLocaleString()}` : ""}
      </p>
      {status.lastError && ERRORS[status.lastError] && <p className="text-destructive">{ERRORS[status.lastError]}</p>}
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy} onClick={() => run(() => phone.syncNow(), "Calls sent")}>
          Send calls now
        </Button>
        <Button variant="ghost" disabled={busy} onClick={turnOff}>
          Turn off
        </Button>
      </div>
    </div>
  );
}

/** Settings → Calls → Phones with the app (admins): who has call tracking on, when each phone
 * last sent a call, and Remove (a lost phone, a rep who leaves). */
export function PhonesWithTheApp() {
  const [rows, setRows] = useState<Awaited<ReturnType<typeof load>> | null>(null);
  async function load() {
    return unwrap(await api.GET("/api/v1/phone/all-devices"));
  }
  useEffect(() => {
    load().then(setRows).catch(() => setRows([]));
  }, []);
  async function remove(id: string) {
    try {
      unwrap(await api.POST("/api/v1/phone/devices/{device_id}/remove", { params: { path: { device_id: id } } }));
      setRows(await load());
      toast.success("Phone removed. It can't send calls any more.");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <div className="surface mt-6 space-y-3 p-4 text-sm">
      <div>
        <h2 className="font-semibold">Phones with the app</h2>
        <p className="text-muted-foreground">Reps turn on call tracking in the Versnq app under My account.</p>
      </div>
      {rows === null ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground">No phones yet.</p>
      ) : (
        <ul className="divide-y">
          {rows.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="font-medium">{d.user_name}</span>
              <span className="text-muted-foreground">
                {[d.device, d.version && `app ${d.version}`, d.last_call_at ? `last call ${new Date(d.last_call_at).toLocaleString()}` : "no calls yet"].filter(Boolean).join(" · ")}
              </span>
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => remove(d.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
