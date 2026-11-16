"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

function keyBytes(base64: string) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** My account → Phone notifications (calls plan C2): new leads, missed calls and due tasks pop
 * up on this phone or browser. On iPhone it works once Core is added to the home screen. */
export function PhoneNotifications() {
  const key = useQuery({ queryKey: ["push-key"], queryFn: async () => unwrap(await api.GET("/api/v1/push/key")) });
  // Rendered only after sign-in, in the browser (never on the server).
  const [supported] = useState(() => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window);
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supported) return;
    navigator.serviceWorker.ready.then((reg) => reg.pushManager.getSubscription()).then((sub) => setEndpoint(sub?.endpoint ?? null)).catch(() => {});
  }, [supported]);

  if (!key.data?.public_key) return null; // not set up on this server yet
  if (!supported)
    return (
      <p className="text-muted-foreground">
        This browser can&apos;t show notifications. On iPhone, first add Core to your home screen (Share → Add to Home Screen), then open it from there.
      </p>
    );

  async function turnOn() {
    setBusy(true);
    try {
      if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications are blocked for this site in your browser settings");
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key.data!.public_key!) });
      const json = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
      unwrap(await api.POST("/api/v1/push/subscriptions", { body: { endpoint: json.endpoint, keys: json.keys } }));
      setEndpoint(sub.endpoint);
      toast.success("Notifications are on for this device");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        unwrap(await api.POST("/api/v1/push/subscriptions/off", { body: { endpoint: sub.endpoint } }));
        await sub.unsubscribe();
      }
      setEndpoint(null);
      toast.success("Notifications are off for this device");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return endpoint ? (
    <Button variant="outline" disabled={busy} onClick={turnOff}>
      Turn off on this device
    </Button>
  ) : (
    <Button disabled={busy} onClick={turnOn}>
      Turn on for this device
    </Button>
  );
}
