"use client";

import { ChevronDown, ChevronUp, Settings2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Popover, PopoverHeading } from "@/components/data-table/popover";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type Column<T> = {
  key: string;
  label: string;
  cell: (row: T) => React.ReactNode;
  /** Server sort key; omit for columns that cannot be sorted. */
  sort?: string;
  /** Always shown and stuck to the left (the record's name). */
  pinned?: boolean;
  hiddenByDefault?: boolean;
  className?: string;
};

export type Paging = { page: number; size: number; sort: string; dir: "asc" | "desc" };
export type Selection = { ids: Set<string>; allMatching: boolean };
export const emptySelection = (): Selection => ({ ids: new Set(), allMatching: false });

type Density = "compact" | "comfortable";
type Prefs = { hidden: string[]; density: Density };

/** Column choices and density, remembered per person and per list (in this browser). */
export function useTablePrefs(tableKey: string, columns: Column<unknown>[]) {
  const storageKey = `versnq.table.${tableKey}`;
  const [prefs, setPrefs] = useState<Prefs>(() => {
    const fallback: Prefs = { hidden: columns.filter((c) => c.hiddenByDefault).map((c) => c.key), density: "compact" };
    try {
      const saved = typeof window !== "undefined" ? window.localStorage.getItem(storageKey) : null;
      return saved ? { ...fallback, ...(JSON.parse(saved) as Prefs) } : fallback;
    } catch {
      return fallback;
    }
  });
  const update = (next: Prefs) => {
    setPrefs(next);
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      /* private mode etc.: the choice just isn't remembered */
    }
  };
  return {
    hidden: new Set(prefs.hidden),
    density: prefs.density,
    toggleColumn: (key: string) =>
      update({ ...prefs, hidden: prefs.hidden.includes(key) ? prefs.hidden.filter((k) => k !== key) : [...prefs.hidden, key] }),
    setDensity: (density: Density) => update({ ...prefs, density }),
  };
}

export function TableTools<T>({ columns, prefs }: { columns: Column<T>[]; prefs: ReturnType<typeof useTablePrefs> }) {
  return (
    <Popover
      align="end"
      trigger={({ toggle }) => (
        <Button size="sm" variant="outline" onClick={toggle}>
          <Settings2 /> Columns
        </Button>
      )}
    >
      <PopoverHeading>Show columns</PopoverHeading>
      {columns.map((c) => (
        <label key={c.key} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent">
          <input type="checkbox" className="accent-primary" checked={!prefs.hidden.has(c.key)} disabled={c.pinned} onChange={() => prefs.toggleColumn(c.key)} />
          {c.label}
        </label>
      ))}
      <PopoverHeading>Row height</PopoverHeading>
      <div className="flex gap-1 px-2 pb-1">
        {(["compact", "comfortable"] as const).map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => prefs.setDensity(d)}
            className={cn("rounded-md border px-2 py-0.5 text-xs capitalize", prefs.density === d && "border-primary bg-primary/10")}
          >
            {d}
          </button>
        ))}
      </div>
    </Popover>
  );
}

/**
 * The one table every list uses: one-line rows, sortable headers, page numbers with totals,
 * select a page or everything matching, a bulk bar, keyboard (J/K move, Enter open, X select),
 * and cards on phones.
 */
export function DataTable<T>({
  columns,
  rows,
  total,
  loading,
  error,
  getId,
  paging,
  onPaging,
  selection,
  onSelection,
  allowAllMatching = true,
  onOpen,
  card,
  bulk,
  prefs,
  noun,
  empty,
}: {
  columns: Column<T>[];
  rows: T[];
  total: number;
  loading?: boolean;
  error?: string | null;
  getId: (row: T) => string;
  paging: Paging;
  onPaging: (p: Paging) => void;
  selection?: Selection;
  onSelection?: (s: Selection) => void;
  allowAllMatching?: boolean;
  onOpen?: (row: T) => void;
  card?: (row: T) => React.ReactNode;
  bulk?: (count: number, clear: () => void) => React.ReactNode;
  prefs: ReturnType<typeof useTablePrefs>;
  noun: string;
  empty?: React.ReactNode;
}) {
  const visible = columns.filter((c) => c.pinned || !prefs.hidden.has(c.key));
  const pages = Math.max(1, Math.ceil(total / paging.size));
  const [cursor, setCursor] = useState(-1);
  const selectable = Boolean(selection && onSelection);
  const pageIds = useMemo(() => rows.map(getId), [rows, getId]);
  const allOnPage = selectable && pageIds.length > 0 && pageIds.every((id) => selection!.allMatching || selection!.ids.has(id));
  const count = selection ? (selection.allMatching ? total : selection.ids.size) : 0;
  const clear = () => onSelection?.({ ids: new Set(), allMatching: false });
  const rowHeight = prefs.density === "compact" ? "h-9" : "h-11";

  const toggle = (id: string) => {
    if (!selection || !onSelection) return;
    const ids = new Set(selection.allMatching ? pageIds : selection.ids);
    if (ids.has(id)) ids.delete(id);
    else ids.add(id);
    onSelection({ ids, allMatching: false });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.metaKey || e.ctrlKey) return;
      if (document.querySelector('[role="dialog"][data-modal], [data-slot="dialog-content"]')) return;
      if (e.key === "j") setCursor((c) => Math.min(rows.length - 1, c + 1));
      if (e.key === "k") setCursor((c) => Math.max(0, c - 1));
      if (e.key === "Enter" && cursor >= 0 && rows[cursor]) onOpen?.(rows[cursor]);
      if (e.key === "x" && cursor >= 0 && rows[cursor]) toggle(getId(rows[cursor]));
      if (e.key === "/") {
        const search = document.querySelector<HTMLInputElement>("[data-table-search]");
        if (search) {
          e.preventDefault();
          search.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const go = (page: number) => {
    setCursor(-1);
    onPaging({ ...paging, page });
  };
  const pageList: (number | "…")[] = [];
  for (let p = 1; p <= pages; p++) {
    if (p === 1 || p === pages || Math.abs(p - paging.page) <= 1) pageList.push(p);
    else if (pageList[pageList.length - 1] !== "…") pageList.push("…");
  }
  const from = total ? (paging.page - 1) * paging.size + 1 : 0;
  const to = Math.min(paging.page * paging.size, total);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      {selectable && allowAllMatching && allOnPage && !selection!.allMatching && total > rows.length && (
        <div className="border-b bg-primary/5 px-4 py-1.5 text-center text-xs">
          All {rows.length} on this page are selected.{" "}
          <button className="font-semibold text-primary" onClick={() => onSelection!({ ids: new Set(), allMatching: true })}>
            Select all {total} matching {noun}
          </button>
        </div>
      )}
      {selection?.allMatching && (
        <div className="border-b bg-primary/5 px-4 py-1.5 text-center text-xs">
          All {total} matching {noun} are selected.{" "}
          <button className="font-semibold text-primary" onClick={clear}>
            Clear selection
          </button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        {error ? (
          <p className="p-6 text-destructive">{error}</p>
        ) : (
          <>
            <table className="hidden w-max min-w-full border-separate border-spacing-0 text-[13px] md:table">
              <thead>
                <tr>
                  {selectable && (
                    <th className="sticky top-0 left-0 z-30 w-9 border-b bg-card pl-4">
                      <input
                        type="checkbox"
                        aria-label="Select this page"
                        className="accent-primary"
                        checked={allOnPage}
                        onChange={() => (allOnPage ? clear() : onSelection!({ ids: new Set(pageIds), allMatching: false }))}
                      />
                    </th>
                  )}
                  {visible.map((c) => {
                    const active = c.sort && paging.sort === c.sort;
                    return (
                      <th
                        key={c.key}
                        className={cn(
                          "sticky top-0 z-20 h-9 border-b bg-card px-3 text-left text-xs font-medium whitespace-nowrap text-muted-foreground",
                          c.pinned && cn(selectable ? "left-9" : "left-0 pl-4", "z-30 shadow-[1px_0_0_var(--border)]"),
                          c.sort && "cursor-pointer select-none hover:text-foreground",
                        )}
                        aria-sort={active ? (paging.dir === "asc" ? "ascending" : "descending") : undefined}
                        onClick={() =>
                          c.sort &&
                          onPaging({ ...paging, page: 1, sort: c.sort, dir: active && paging.dir === "asc" ? "desc" : "asc" })
                        }
                      >
                        {c.label}
                        {active && (paging.dir === "asc" ? <ChevronUp className="ml-0.5 inline size-3" /> : <ChevronDown className="ml-0.5 inline size-3" />)}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className={cn(loading && "opacity-60")}>
                {rows.map((row, i) => {
                  const id = getId(row);
                  const isSelected = Boolean(selection?.allMatching || selection?.ids.has(id));
                  return (
                    <tr
                      key={id}
                      onClick={() => {
                        setCursor(i);
                        onOpen?.(row);
                      }}
                      className={cn(
                        "group cursor-pointer bg-card hover:bg-accent/60",
                        isSelected && "bg-primary/[0.06]",
                        cursor === i && "shadow-[inset_2px_0_0_var(--primary)]",
                      )}
                    >
                      {selectable && (
                        <td className={cn("sticky left-0 z-10 border-b bg-inherit pl-4", rowHeight)} onClick={(e) => e.stopPropagation()}>
                          <input type="checkbox" aria-label="Select row" className="accent-primary" checked={isSelected} onChange={() => toggle(id)} />
                        </td>
                      )}
                      {visible.map((c) => (
                        <td
                          key={c.key}
                          className={cn(
                            "border-b px-3 whitespace-nowrap",
                            rowHeight,
                            c.pinned && cn("sticky z-10 bg-inherit shadow-[1px_0_0_var(--border)]", selectable ? "left-9" : "left-0 pl-4"),
                            c.className,
                          )}
                        >
                          {c.cell(row)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <ul className={cn("divide-y md:hidden", loading && "opacity-60")}>
              {rows.map((row) => {
                const id = getId(row);
                return (
                  <li key={id} className="flex items-start gap-3 px-4 py-3" onClick={() => onOpen?.(row)}>
                    {selectable && (
                      <input
                        type="checkbox"
                        aria-label="Select row"
                        className="mt-1 accent-primary"
                        checked={Boolean(selection?.allMatching || selection?.ids.has(id))}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggle(id)}
                      />
                    )}
                    <div className="min-w-0 flex-1">{card ? card(row) : visible[0]?.cell(row)}</div>
                  </li>
                );
              })}
            </ul>
            {!loading && rows.length === 0 && <div className="p-12 text-center text-muted-foreground">{empty ?? `No ${noun} here.`}</div>}
          </>
        )}
      </div>
      <div className="flex min-h-11 flex-wrap items-center gap-3 border-t px-4 py-1.5 text-xs text-muted-foreground">
        <span className="tabular-nums">
          {from}–{to} of {total} {noun}
        </span>
        <label className="hidden items-center gap-1 sm:flex">
          Rows
          <select
            aria-label="Rows per page"
            className="rounded border bg-card px-1 py-0.5"
            value={paging.size}
            onChange={(e) => onPaging({ ...paging, page: 1, size: Number(e.target.value) })}
          >
            {[25, 50, 100].map((n) => (
              <option key={n}>{n}</option>
            ))}
          </select>
        </label>
        <nav aria-label="Pages" className="ml-auto flex items-center gap-0.5">
          <PageButton label="Previous page" disabled={paging.page <= 1} onClick={() => go(paging.page - 1)}>
            ‹
          </PageButton>
          {pageList.map((p, i) =>
            p === "…" ? (
              <span key={`gap-${i}`} className="px-1">
                …
              </span>
            ) : (
              <PageButton key={p} label={`Page ${p}`} current={p === paging.page} onClick={() => go(p)}>
                {p}
              </PageButton>
            ),
          )}
          <PageButton label="Next page" disabled={paging.page >= pages} onClick={() => go(paging.page + 1)}>
            ›
          </PageButton>
        </nav>
      </div>
      {bulk && count > 0 && (
        <div className="absolute bottom-14 left-1/2 z-40 flex w-max max-w-[calc(100%-1rem)] -translate-x-1/2 flex-wrap items-center gap-1.5 rounded-xl bg-foreground py-1.5 pr-1.5 pl-3.5 text-background shadow-xl">
          <span className="text-xs font-semibold whitespace-nowrap">{count} selected</span>
          {bulk(count, clear)}
          <button aria-label="Clear selection" className="rounded-md p-1 hover:bg-background/15" onClick={clear}>
            <X className="size-4" />
          </button>
        </div>
      )}
    </div>
  );
}

function PageButton({
  children,
  onClick,
  disabled,
  current,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  current?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-current={current ? "page" : undefined}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-7 min-w-7 place-items-center rounded-md px-1.5 tabular-nums hover:bg-accent disabled:opacity-30",
        current && "bg-primary/10 font-semibold text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** Light button style for actions inside the dark bulk bar. */
export function BulkButton({ children, onClick, danger }: { children: React.ReactNode; onClick?: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("h-7 rounded-md border border-background/25 px-2.5 text-xs font-medium whitespace-nowrap hover:bg-background/15", danger && "text-red-300")}
    >
      {children}
    </button>
  );
}
