"use client";

import { PageHeader } from "@/components/app/app-shell";
import { useAuth } from "@/lib/auth";
import { useLabels } from "@/lib/settings";

export default function MyDayPage() {
  const { me } = useAuth();
  const label = useLabels();
  return (
    <>
      <PageHeader title="My Day" />
      <div className="mx-auto w-full max-w-2xl p-8">
        <h2 className="text-lg font-semibold">Good to see you, {me?.name.split(" ")[0]}.</h2>
        <p className="mt-1 text-muted-foreground">
          Your {label("lead", true).toLowerCase()}, follow-ups and tasks will appear here once the CRM module
          arrives (Phase 2). For now you can manage your workspace from the sidebar.
        </p>
      </div>
    </>
  );
}
