"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { LeadPanel } from "@/components/crm/lead-panel";
import { useLabels } from "@/lib/settings";

export default function LeadPage() {
  const { id } = useParams<{ id: string }>();
  const label = useLabels();
  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="border-b px-4 py-2">
        <Link href="/leads" className="text-xs text-muted-foreground hover:underline">
          ← {label("lead", true)}
        </Link>
      </div>
      <LeadPanel key={id} leadId={id} />
    </div>
  );
}
