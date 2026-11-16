"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** Settings → Calls → your own Twilio account (calls plan C3). */
export function TwilioSettings() {
  const qc = useQueryClient();
  const current = useQuery({ queryKey: ["calling-twilio"], queryFn: async () => unwrap(await api.GET("/api/v1/calling/twilio")) });
  const [sid, setSid] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [numbers, setNumbers] = useState<string | null>(null);
  const [forward, setForward] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const d = current.data;
  if (!d) return null;
  const v = { sid: sid ?? d.account_sid ?? "", numbers: numbers ?? (d.numbers ?? []).join(", "), forward: forward ?? d.forward_to ?? "" };

  async function save() {
    setSaving(true);
    try {
      unwrap(
        await api.PUT("/api/v1/calling/twilio", {
          body: {
            account_sid: v.sid.trim(),
            auth_token: token.trim() || null,
            numbers: v.numbers.split(/[,\n]/).map((n) => n.trim()).filter(Boolean),
            forward_to: v.forward.trim() || null,
          },
        }),
      );
      setToken("");
      qc.invalidateQueries({ queryKey: ["calling-twilio"] });
      qc.invalidateQueries({ queryKey: ["my-phone"] });
      toast.success("Twilio is connected");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function disconnect() {
    if (!confirm("Disconnect Twilio? The Call button goes back to the phone's own dialer.")) return;
    unwrap(await api.DELETE("/api/v1/calling/twilio"));
    qc.invalidateQueries({ queryKey: ["calling-twilio"] });
    qc.invalidateQueries({ queryKey: ["my-phone"] });
  }

  return (
    <div className="surface mt-6 space-y-4 p-4 text-sm" data-testid="twilio-settings">
      <div>
        <h2 className="font-semibold">Calling with your own Twilio account {d.connected && <span className="text-xs font-normal text-emerald-600">· connected</span>}</h2>
        <p className="text-xs text-muted-foreground">
          The Call button rings the rep&apos;s own phone first, then connects the lead. Calls to your Twilio numbers ring the lead&apos;s owner, then your main number;
          unanswered callers can leave a voicemail. Every call is logged with its recording. Twilio bills your account for the minutes.
          {d.test_mode && " (Test mode on this server: nothing reaches Twilio.)"}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="tw-sid">Account SID</Label>
          <Input id="tw-sid" placeholder="AC…" value={v.sid} onChange={(e) => setSid(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tw-token">Auth token</Label>
          <Input id="tw-token" type="password" placeholder={d.connected ? "Saved — type a new one to change it" : ""} value={token} onChange={(e) => setToken(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tw-numbers">Your Twilio numbers</Label>
          <Input id="tw-numbers" placeholder="+14155550100, +44…" value={v.numbers} onChange={(e) => setNumbers(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="tw-forward">Main number (when the owner doesn&apos;t answer)</Label>
          <Input id="tw-forward" placeholder="Optional" value={v.forward} onChange={(e) => setForward(e.target.value)} />
        </div>
      </div>
      {d.connected && (
        <div className="space-y-1.5">
          <Label>In Twilio, for each number: &quot;A call comes in&quot; → Webhook, HTTP POST, this address</Label>
          <div className="flex gap-2">
            <Input readOnly value={d.voice_url} aria-label="Voice address for Twilio" className="font-mono text-xs" />
            <Button type="button" variant="outline" onClick={() => navigator.clipboard.writeText(d.voice_url).then(() => toast.success("Copied"))}>
              <Copy /> Copy
            </Button>
          </div>
        </div>
      )}
      <div className="flex gap-2">
        <Button onClick={save} disabled={saving || !v.sid || !v.numbers || (!d.connected && !token)}>
          {d.connected ? "Save" : "Connect Twilio"}
        </Button>
        {d.connected && (
          <Button variant="outline" onClick={disconnect}>
            Disconnect
          </Button>
        )}
      </div>
    </div>
  );
}

/** My account → the phone the Call button rings first (calls plan C3). */
export function MyCallingPhone() {
  const qc = useQueryClient();
  const mine = useQuery({ queryKey: ["my-phone"], queryFn: async () => unwrap(await api.GET("/api/v1/calling/my-phone")) });
  const [phone, setPhone] = useState<string | null>(null);
  if (!mine.data) return null;
  const value = phone ?? mine.data.phone ?? "";
  async function save() {
    try {
      unwrap(await api.PUT("/api/v1/calling/my-phone", { body: { phone: value.trim() || null } }));
      setPhone(null);
      qc.invalidateQueries({ queryKey: ["my-phone"] });
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="space-y-1.5">
        <Label htmlFor="my-phone">Your mobile number</Label>
        <Input id="my-phone" className="w-56" placeholder="+91 98…" value={value} onChange={(e) => setPhone(e.target.value)} />
      </div>
      <Button variant="outline" onClick={save}>
        Save
      </Button>
      {!mine.data.calling && <p className="w-full text-xs text-muted-foreground">Used once your company connects its calling account.</p>}
    </div>
  );
}
