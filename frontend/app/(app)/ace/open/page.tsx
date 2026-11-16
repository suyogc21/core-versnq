"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

/** C13: sends a signed-in person to ACE's console with a one-time code. ACE also sends people
 * here (sign-in first, then back to ACE). */
export default function OpenAcePage() {
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // one code per visit
    started.current = true;
    (async () => {
      try {
        const r = unwrap(await api.POST("/api/v1/ace/console-code"));
        window.location.replace(r.url);
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, []);
  return (
    <div className="grid h-full place-items-center p-8 text-center">
      {error ? (
        <p className="text-muted-foreground">
          ACE can&apos;t be opened: {error}. If you need it, ask your company&apos;s Owner or Admin.
        </p>
      ) : (
        <p className="text-muted-foreground">Opening ACE…</p>
      )}
    </div>
  );
}
