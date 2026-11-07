"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { ChangePasswordScreen, TwoFactorSetupScreen } from "@/components/app/sign-in";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Companies" },
  { href: "/staff", label: "Staff" },
  { href: "/audit", label: "Audit log" },
];

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const { status, me, logout } = useAuth();
  const router = useRouter();
  const path = usePathname();

  useEffect(() => {
    if (status === "signed-out") router.replace("/login");
  }, [status, router]);

  if (status !== "signed-in" || !me) {
    return <div className="grid h-screen place-items-center text-muted-foreground">Loading…</div>;
  }
  // The backend enforces these too; the screens just guide the staff member through them.
  if (me.restrictions.includes("password_change_required")) return <ChangePasswordScreen />;
  if (me.restrictions.includes("two_factor_setup_required")) return <TwoFactorSetupScreen />;

  return (
    <div className="min-h-screen">
      <header className="flex h-12 items-center gap-6 border-b px-6">
        <span className="font-semibold">
          Versnq <span className="font-normal text-muted-foreground">staff</span>
        </span>
        <nav className="flex gap-1">
          {NAV.map((n) => {
            const active = n.href === "/" ? path === "/" || path.startsWith("/companies") : path.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={cn(
                  "rounded-md px-2.5 py-1 text-muted-foreground hover:bg-accent hover:text-foreground",
                  active && "bg-accent text-foreground",
                )}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="text-muted-foreground">{me.email}</span>
          <Button size="sm" variant="outline" onClick={logout}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl p-6">{children}</main>
    </div>
  );
}
