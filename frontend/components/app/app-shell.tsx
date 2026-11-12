"use client";

import { BadgeCheck, Boxes, ChartColumn, Contact, Handshake, Inbox, LogOut, Send, Star, type LucideIcon, Menu, Moon, ReceiptText, Settings, Sun, Sunrise, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useState } from "react";

import { NotificationBell } from "@/components/app/notification-bell";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { useKeyAccountsOn } from "@/lib/accounts";
import { useMoneyOn } from "@/lib/money";
import { useRecordTypes } from "@/lib/records";
import { SETTINGS_PAGES, settingsPageFor } from "@/lib/settings-nav";
import { useLabels, useWorkspaceSettings } from "@/lib/settings";
import { useInboxCounts } from "@/lib/inbox";

type NavItem = { href: string; label: string; icon: LucideIcon; permission?: string; count?: number };

const MAIN: NavItem[] = [
  { href: "/", label: "My Day", icon: Sunrise },
  { href: "/leads", label: "lead", icon: Contact, permission: "leads.edit" }, // label from settings
  { href: "/deals", label: "deal", icon: Handshake, permission: "deals.edit" },
  { href: "/customers", label: "customer", icon: BadgeCheck, permission: "customers.read" },
];


function initials(name: string) {
  return name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const path = usePathname();
  const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 font-medium text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground",
        active && "bg-card text-foreground shadow-card hover:bg-card",
      )}
    >
      <Icon className="size-4 opacity-80" />
      {item.label}
      {item.count ? (
        <span className="ml-auto rounded-full bg-primary px-1.5 text-[10px] font-semibold text-primary-foreground tabular-nums" aria-label={`${item.count} unread`}>
          {item.count}
        </span>
      ) : null}
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, can, logout } = useAuth();
  const path = usePathname();
  const { resolvedTheme, setTheme } = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  useWorkspaceSettings(); // loads labels and applies the workspace colour
  const label = useLabels();
  const recordTypes = useRecordTypes();
  const moneyOn = useMoneyOn();
  const keyOn = useKeyAccountsOn();
  const inboxCounts = useInboxCounts(!!me && can("inbox.reply"));
  if (!me) return null;
  const mainItems = [
    ...MAIN.filter((i) => !i.permission || can(i.permission)).map((i) => (i.href === "/" ? i : { ...i, label: label(i.label, true) })),
    ...(can("inbox.reply") ? [{ href: "/inbox", label: "Inbox", icon: Inbox, count: inboxCounts.data?.mine_unread }] : []),
    ...(keyOn && can("leads.edit") ? [{ href: "/key-accounts", label: "Key accounts", icon: Star }] : []),
    ...(moneyOn && can("invoices.read") ? [{ href: "/money", label: "Money", icon: ReceiptText }] : []),
    ...(["leads.edit", "dashboards.team", "dashboards.business", "dashboards.money"].some((c) => can(c))
      ? [{ href: "/dashboards", label: "Dashboards", icon: ChartColumn }]
      : []),
    ...(can("sequences.manage") ? [{ href: "/sequences", label: "Sequences", icon: Send }] : []),
    // Each record type the company made (Property, Batch...) that this person may view.
    ...(me.restrictions.length ? [] : (recordTypes.data ?? [])).map((t) => ({ href: `/r/${t.key}`, label: t.plural, icon: Boxes })),
  ];
  // One Settings entry for everything set up once; shown when any settings page is allowed.
  const workspaceItems: NavItem[] = SETTINGS_PAGES.some((p) => can(p.permission))
    ? [{ href: "/settings", label: "Settings", icon: Settings }]
    : [];
  // Typing an admin address directly gets a clear refusal (the backend refuses the data too).
  const settingsPage = settingsPageFor(path);
  const locked =
    (settingsPage && !can(settingsPage.permission)) || (path === "/settings" && workspaceItems.length === 0)
      ? { label: settingsPage?.title ?? "Settings" }
      : null;
  const close = () => setMenuOpen(false);

  const workspaceBadge = (
    <div className="flex min-w-0 items-center gap-2">
      <div className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary text-xs font-bold text-primary-foreground">
        {me.tenant.name.charAt(0).toUpperCase()}
      </div>
      <div className="min-w-0">
        <div className="truncate font-semibold">{me.tenant.name}</div>
        <div className="truncate text-[11px] text-muted-foreground">{me.tenant.slug}</div>
      </div>
    </div>
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden md:flex-row">
      {/* Phone: a top bar with a menu button; the sidebar slides in over the page. */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b bg-sidebar px-2 md:hidden">
        <button aria-label="Open menu" className="rounded p-2 hover:bg-accent" onClick={() => setMenuOpen(true)}>
          <Menu className="size-5" />
        </button>
        {workspaceBadge}
        {can("leads.edit") && (
          <div className="ml-auto">
            <NotificationBell />
          </div>
        )}
      </div>
      {menuOpen && <div className="fixed inset-0 z-40 bg-black/40 md:hidden" onClick={close} aria-hidden />}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 shrink-0 flex-col gap-0.5 border-r bg-sidebar px-3 py-3 transition-transform md:static md:w-56 md:translate-x-0",
          menuOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="mb-3 flex items-center justify-between rounded-md px-1.5 py-1">
          {workspaceBadge}
          {can("leads.edit") && (
            <div className="hidden md:block">
              <NotificationBell />
            </div>
          )}
          <button aria-label="Close menu" className="rounded p-1 hover:bg-accent md:hidden" onClick={close}>
            <X className="size-4" />
          </button>
        </div>
        {mainItems.map((i) => (
          <NavLink key={i.href} item={i} onNavigate={close} />
        ))}
        {workspaceItems.length > 0 && (
          <>
            <div className="mt-2 border-t pt-2" />
            {workspaceItems.map((i) => (
              <NavLink key={i.href} item={i} onNavigate={close} />
            ))}
          </>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-2 border-t px-2 pt-2.5">
          <Link
            href="/account"
            onClick={close}
            title="My account"
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md hover:opacity-80"
          >
            <div className="grid size-6 shrink-0 place-items-center rounded-full bg-primary/15 text-[10px] font-semibold text-foreground">
              {initials(me.name)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{me.name}</div>
              <div className="truncate text-[11px] text-muted-foreground">{me.role.name}</div>
            </div>
          </Link>
          <button
            aria-label="Toggle dark mode"
            className="rounded p-1 text-muted-foreground hover:bg-accent"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          >
            {resolvedTheme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
          <button aria-label="Sign out" className="rounded p-1 text-muted-foreground hover:bg-accent" onClick={logout}>
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>
      <main className="flex min-w-0 flex-1 flex-col overflow-auto bg-background">
        {locked ? (
          <>
            <PageHeader title={locked.label} />
            <p className="p-8 text-center text-muted-foreground">You don&apos;t have permission to do that.</p>
          </>
        ) : (
          children
        )}
      </main>
    </div>
  );
}

/** Page title bar, matching the mockup's top bar. */
export function PageHeader({
  title,
  count,
  actions,
  back,
}: {
  title: string;
  count?: number;
  actions?: React.ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <div className="sticky top-0 z-20 flex min-h-13 shrink-0 flex-wrap items-center gap-x-2.5 gap-y-2 border-b bg-background/80 px-4 py-2 backdrop-blur-xl backdrop-saturate-150 sm:px-6">
      {back && (
        <>
          <Link href={back.href} className="text-sm text-muted-foreground hover:text-foreground">
            {back.label}
          </Link>
          <span className="text-muted-foreground">/</span>
        </>
      )}
      <h1 className="text-[15px] font-semibold tracking-tight">{title}</h1>
      {count !== undefined ? <span className="text-muted-foreground">{count}</span> : null}
      {actions ? <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">{actions}</div> : null}
    </div>
  );
}
