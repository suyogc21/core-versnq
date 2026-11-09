"use client";

import Link from "next/link";

import { PageHeader } from "@/components/app/app-shell";
import { useAuth } from "@/lib/auth";
import { SETTINGS_PAGES } from "@/lib/settings-nav";

/** One home for everything that is set up once; the sidebar keeps the places you work in. */
export default function SettingsHome() {
  const { can } = useAuth();
  const pages = SETTINGS_PAGES.filter((p) => can(p.permission));
  const groups = [...new Set(pages.map((p) => p.group))];
  return (
    <>
      <PageHeader title="Settings" />
      <div className="mx-auto w-full max-w-4xl space-y-8 p-4 sm:p-8">
        {pages.length === 0 && <p className="text-center text-muted-foreground">You don&apos;t have permission to do that.</p>}
        {groups.map((g) => (
          <section key={g} className="space-y-2">
            <h2 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{g}</h2>
            <div className="grid gap-2 sm:grid-cols-2">
              {pages
                .filter((p) => p.group === g)
                .map((p) => {
                  const Icon = p.icon;
                  return (
                    <Link key={p.href} href={p.href} className="flex gap-3 rounded-lg border p-3 hover:bg-accent">
                      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                      <span>
                        <span className="block text-sm font-medium">{p.title}</span>
                        <span className="block text-xs text-muted-foreground">{p.hint}</span>
                      </span>
                    </Link>
                  );
                })}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
