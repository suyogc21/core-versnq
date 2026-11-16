"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverHeading } from "@/components/data-table/popover";
import { cn } from "@/lib/utils";

export type Option = { value: string; label: string };

/** "+ Stage" when empty; "Stage: New, Contacted ✕" when set. Tick several values. */
export function FilterChip({
  label,
  options,
  values,
  onChange,
}: {
  label: string;
  options: Option[];
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const on = values.length > 0;
  const names = values.map((v) => options.find((o) => o.value === v)?.label ?? v);
  return (
    <Popover
      trigger={({ toggle }) => (
        <span
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-md border border-dashed px-2 text-xs whitespace-nowrap text-muted-foreground",
            on && "border-solid border-primary/40 bg-primary/10 text-foreground",
          )}
        >
          <button type="button" onClick={toggle} className="inline-flex items-center gap-1">
            {on ? (
              <>
                {label}: {names.slice(0, 2).join(", ")}
                {names.length > 2 && ` +${names.length - 2}`}
              </>
            ) : (
              <>+ {label}</>
            )}
          </button>
          {on && (
            <button type="button" aria-label={`Clear ${label}`} className="opacity-60 hover:opacity-100" onClick={() => onChange([])}>
              <X className="size-3" />
            </button>
          )}
        </span>
      )}
    >
      <PopoverHeading>{label}</PopoverHeading>
      <OptionSearch options={options}>
        {(shown) =>
          shown.map((o) => (
        <label key={o.value} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent">
          <input
            type="checkbox"
            className="accent-primary"
            checked={values.includes(o.value)}
            onChange={(e) => onChange(e.target.checked ? [...values, o.value] : values.filter((v) => v !== o.value))}
          />
          {o.label}
        </label>
          ))
        }
      </OptionSearch>
    </Popover>
  );
}

/** Long lists (e.g. 250 owners) get a search box; short ones don't need it. */
export function OptionSearch({ options, children }: { options: Option[]; children: (shown: Option[]) => React.ReactNode }) {
  const [term, setTerm] = useState("");
  const shown = term ? options.filter((o) => o.label.toLowerCase().includes(term.toLowerCase())) : options;
  return (
    <>
      {options.length > 8 && (
        <input
          autoFocus
          aria-label="Search options"
          placeholder="Search…"
          className="mx-1 mb-1 h-7 w-[calc(100%-0.5rem)] rounded-md border bg-card px-2 text-xs outline-none"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
      )}
      {children(shown.slice(0, 200))}
      {shown.length === 0 && <div className="px-2 py-1.5 text-xs text-muted-foreground">No match</div>}
    </>
  );
}

export type View = { key: string; label: string; count?: number; alert?: boolean };

/** Saved views as tabs with live counts (red when something needs attention). */
export function ViewTabs({ views, active, onChange }: { views: View[]; active: string; onChange: (key: string) => void }) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto border-b px-3 [scrollbar-width:none]" role="tablist">
      {views.map((v) => (
        <button
          key={v.key}
          role="tab"
          aria-selected={active === v.key}
          onClick={() => onChange(v.key)}
          className={cn(
            "-mb-px border-b-2 border-transparent px-2.5 pt-2 pb-2 text-[13px] whitespace-nowrap text-muted-foreground hover:text-foreground",
            active === v.key && "border-primary font-medium text-foreground",
          )}
        >
          {v.label}
          {v.count !== undefined && (
            <span className={cn("ms-1.5 text-xs tabular-nums text-muted-foreground", v.alert && v.count > 0 && "text-destructive")}>{v.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}
