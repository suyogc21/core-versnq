"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

/** The 10 one-time backup codes, shown once (go-live G-4): copy, download, then confirm. */
export function BackupCodes({ codes, onDone }: { codes: string[]; onDone: () => void | Promise<void> }) {
  const [saved, setSaved] = useState(false);
  const text = `Versnq backup codes (each works once, in place of the app's code)\n\n${codes.join("\n")}\n`;
  return (
    <div className="space-y-3" data-testid="backup-codes">
      <p className="text-sm">
        <strong>Save these backup codes</strong> somewhere safe (a password manager or printed). If you lose your phone, each one signs you in once. They
        are shown only now.
      </p>
      <ul className="grid grid-cols-2 gap-1 rounded-lg border bg-muted/40 p-3 font-mono text-sm">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(text);
              toast.success("Copied");
            } catch {
              toast.error("Copy didn't work; select the codes instead");
            }
          }}
        >
          Copy
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            const a = document.createElement("a");
            a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
            a.download = "versnq-backup-codes.txt";
            a.click();
            URL.revokeObjectURL(a.href);
          }}
        >
          Download
        </Button>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I saved them
      </label>
      <Button type="button" className="w-full" disabled={!saved} onClick={() => onDone()}>
        Done
      </Button>
    </div>
  );
}
