"use client";

import { useSyncExternalStore } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** The workspace slug from the address (acme.core.versnq.in -> acme). */
const noSubscription = () => () => {};

export function useWorkspaceSlug(): string {
  return useSyncExternalStore(
    noSubscription,
    () => window.location.hostname.split(".")[0],
    () => "", // server render: no address bar
  );
}

export function AuthCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  const slug = useWorkspaceSlug();
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-4">
        <div className="flex items-center justify-center gap-2 text-muted-foreground">
          <div className="grid size-7 place-items-center rounded-lg bg-primary text-xs font-bold text-primary-foreground">
            {slug.charAt(0).toUpperCase() || "V"}
          </div>
          <span className="font-medium text-foreground">{slug}</span>
          <span>· Versnq Core</span>
        </div>
        <Card className="shadow-float [--card-spacing:--spacing(6)]">
          <CardHeader>
            <CardTitle className="text-xl font-semibold tracking-tight">{title}</CardTitle>
            {description ? <CardDescription>{description}</CardDescription> : null}
          </CardHeader>
          <CardContent>{children}</CardContent>
        </Card>
      </div>
    </main>
  );
}
