"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** A small anchored panel that stays open while you tick several things; closes on outside
 * click or Escape. */
export function Popover({
  trigger,
  children,
  align = "start",
  className,
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => React.ReactNode;
  children: React.ReactNode | ((close: () => void) => React.ReactNode);
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const close = () => setOpen(false);
  return (
    <div ref={ref} className="relative inline-block">
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div
          role="dialog"
          className={cn(
            "absolute top-full z-50 mt-1 max-h-80 min-w-52 overflow-auto rounded-lg border bg-popover p-1 text-sm text-popover-foreground shadow-lg",
            align === "end" ? "end-0" : "start-0",
            className,
          )}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}

export function PopoverHeading({ children }: { children: React.ReactNode }) {
  return <div className="px-2 py-1 text-[11px] text-muted-foreground">{children}</div>;
}

export function PopoverItem({ children, onClick, active }: { children: React.ReactNode; onClick?: () => void; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start hover:bg-accent", active && "font-medium")}
    >
      {children}
    </button>
  );
}
