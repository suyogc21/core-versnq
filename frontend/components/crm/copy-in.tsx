"use client";

import { Copy } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

/** A copy-in address with Copy and New address buttons (step 9b-2). */
export function CopyInAddress({ address, live, onReset }: { address: string; live: boolean; onReset: () => void }) {
  return (
    <div className="space-y-2" data-copy-in>
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-muted px-2 py-1 text-xs break-all">{address}</code>
        <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(address).then(() => toast.success("Copied"))}>
          <Copy className="size-3.5" /> Copy
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => window.confirm("Make a new address? The current one stops working at once.") && onReset()}
        >
          New address
        </Button>
      </div>
      {!live && (
        <p className="text-xs text-amber-700 dark:text-amber-300">Not working yet: this address starts receiving email when your company&apos;s email goes live.</p>
      )}
    </div>
  );
}
