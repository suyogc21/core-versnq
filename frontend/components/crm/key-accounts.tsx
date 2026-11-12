"use client";

import { Star } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { HEALTH, TIER, useKeyAccountsOn, useLeadKeyAccount, useRefreshAccounts } from "@/lib/accounts";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function TierPill({ tier }: { tier: string }) {
  const t = TIER[tier] ?? TIER.growth;
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", t.tone)}>{t.label}</span>;
}

export function HealthDot({ health, withLabel = true }: { health: string; withLabel?: boolean }) {
  const h = HEALTH[health] ?? HEALTH.on_track;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" title={h.label}>
      <span className={cn("size-2 rounded-full", h.dot)} />
      {withLabel && h.label}
    </span>
  );
}

/** On an organisation's page: its key-account badge, or "Mark as key account". */
export function KeyAccountBadge({ leadId, kind }: { leadId: string; kind: string }) {
  const { can } = useAuth();
  const on = useKeyAccountsOn();
  const router = useRouter();
  const refresh = useRefreshAccounts();
  const [busy, setBusy] = useState(false);
  const acc = useLeadKeyAccount(leadId, on && kind === "organisation");
  if (!on || kind !== "organisation" || acc.isLoading) return null;
  if (acc.data) {
    return (
      <Link href={`/key-accounts/${acc.data.id}`} className="inline-flex items-center gap-1.5 rounded-full bg-violet-500/10 px-2.5 py-1 text-xs font-medium text-violet-700 hover:underline dark:text-violet-300">
        <Star className="size-3.5" /> Key account · {TIER[acc.data.tier]?.label}
      </Link>
    );
  }
  if (!can("key_accounts.manage")) return null;
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const made = unwrap(await api.POST("/api/v1/key-accounts", { body: { org_lead_id: leadId, tier: "growth" } }));
          refresh();
          router.push(`/key-accounts/${made.id}`);
        } catch (e) {
          toast.error((e as Error).message);
          setBusy(false);
        }
      }}
    >
      <Star /> Mark as key account
    </Button>
  );
}
