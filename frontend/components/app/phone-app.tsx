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
  folder?: string | null;
  pendingRecordings?: number;
  recordingsFound?: number;
};
type VersnqPhone = {
  info(): Promise<PhoneStatus>;
  requestCallPermission(): Promise<PhoneStatus>;
  connect(o: { token: string }): Promise<PhoneStatus>;
  disconnect(): Promise<PhoneStatus>;
  syncNow(): Promise<PhoneStatus>;
  pickRecordingFolder(): Promise<PhoneStatus>;
  forgetRecordingFolder(): Promise<PhoneStatus>;
  unknownCalls(): Promise<{ calls: UnknownCall[] }>;
  sendUnknown(o: { id: string }): Promise<{ tracked: boolean }>;
  dismissUnknown(o: { id: string }): Promise<void>;
  /** Places the call from the rep's SIM (asks once; else opens the phone's dialer). App 0.6.0+. */
  dial?(o: { number: string }): Promise<{ direct: boolean }>;
};

/** A call with a number Core doesn't know, kept only on the phone until the rep decides. */
export type UnknownCall = { id: string; number: string; direction: "in" | "out"; status: string; date: number; seconds: number };

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
      <UnknownLink phone={phone} />
      <Recordings status={status} busy={busy} run={run} phone={phone} />
    </div>
  );
}

/** "Calls not in Core (3)": calls with numbers that aren't a lead, waiting for the rep. */
function UnknownLink({ phone }: { phone: VersnqPhone }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    phone
      .unknownCalls()
      .then((r) => setCount(r.calls.length))
      .catch(() => {});
  }, [phone]);
  if (!count) return null;
  return (
    <a href="/calls/unknown" className="block font-medium underline">
      {count === 1 ? "1 call isn't in Core: who was it?" : `${count} calls aren't in Core: who were they?`}
    </a>
  );
}

/** Recordings (C4.3): the folder the phone's own recorder saves calls to. */
function Recordings({ status, busy, run, phone }: { status: PhoneStatus; busy: boolean; run: (a: () => Promise<PhoneStatus>, ok?: string) => Promise<void>; phone: VersnqPhone }) {
  const pick = () =>
    run(async () => {
      const s = await phone.pickRecordingFolder();
      if (s.folder && s.recordingsFound === 0) toast.warning("No recordings in that folder yet. Make a test call, then check again.");
      else if (s.folder) toast.success(`Found ${s.recordingsFound} recordings. New calls' recordings will go to the lead.`);
      return s;
    });
  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <h3 className="font-medium">Recordings</h3>
      {status.folder ? (
        <>
          <p>
            From <span className="font-medium">{status.folder}</span>
            {status.pendingRecordings ? ` · ${status.pendingRecordings} waiting to upload` : ""}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" disabled={busy} onClick={pick}>
              Change folder
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => run(() => phone.forgetRecordingFolder(), "Recordings are off on this phone")}>
              Stop sending recordings
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-muted-foreground">
            If your phone records calls itself, choose the folder it saves them to. Each call&apos;s recording then goes to the lead, so your manager can listen and ACE can summarise it.
          </p>
          <p className="text-muted-foreground">Where it usually is (it differs by phone and version):</p>
          <ul className="list-disc ps-5 text-muted-foreground">
            <li>Samsung: Recordings → Call</li>
            <li>Xiaomi, Redmi, Poco: MIUI → sound_recorder → call_rec</li>
            <li>OnePlus, Oppo, Realme: Music → Recordings → Call Recordings</li>
            <li>Others: open the phone&apos;s Files app and look for &quot;Call&quot; or &quot;Recordings&quot;</li>
          </ul>
          <Button size="sm" disabled={busy} onClick={pick}>
            Choose recorder folder
          </Button>
        </>
      )}
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
              <Button size="sm" variant="ghost" className="ms-auto" onClick={() => remove(d.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export const APP_DOWNLOAD = "/app/versnq-core.apk";

/** "Get the Android app": shown outside the app, once the server has the app file. */
export function GetTheApp({ wrap = (n) => n }: { wrap?: (n: React.ReactNode) => React.ReactNode }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (navigator.userAgent.includes("VersnqCoreApp/")) return;
    fetch(APP_DOWNLOAD, { method: "HEAD" })
      .then((r) => setReady(r.ok))
      .catch(() => {});
  }, []);
  if (!ready) return null;
  return wrap(
    <div className="space-y-2 text-sm">
      <p className="text-muted-foreground">
        On an Android phone, download the app and open the file. Android asks once to allow installing it. In the app, type your company&apos;s address, sign in, then
        turn on call tracking under My account.
      </p>
      <a className="inline-flex rounded-md bg-primary px-3 py-2 font-medium text-primary-foreground" href={APP_DOWNLOAD} download>
        Download the Android app
      </a>
    </div>,
  );
}
