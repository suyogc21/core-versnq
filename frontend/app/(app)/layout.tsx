"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/app/app-shell";
import { ChangePasswordScreen } from "@/components/app/restriction-screens";
import { useAuth } from "@/lib/auth";

export default function SignedInLayout({ children }: { children: React.ReactNode }) {
  const { status, me } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "signed-out") router.replace("/login");
  }, [status, router]);

  if (status !== "signed-in" || !me) {
    return <div className="grid h-screen place-items-center text-muted-foreground">Loading…</div>;
  }
  // The backend enforces these too; the screens just guide the user through them in order.
  if (me.restrictions.includes("password_change_required")) return <ChangePasswordScreen />;
  return <AppShell>{children}</AppShell>;
}
