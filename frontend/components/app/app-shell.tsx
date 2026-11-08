"use client";

import { Activity, Building2, Contact, LogOut, Menu, Moon, Route, Settings, Shield, SlidersHorizontal, Sun, Sunrise, Users, UsersRound, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useState } from "react";

import { NotificationBell } from "@/components/app/notification-bell";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { useLabels, useWorkspaceSettings } from "@/lib/settings";

type NavItem = { href: string; label: string; icon: typeof Users; permission?: string };

const MAIN: NavItem[] = [
  { href: "/", label: "My Day", icon: Sunrise },
  { href: "/leads", label: "lead", icon: Contact, permission: "leads.edit" }, // label from settings
];
const WORKSPACE: NavItem[] = [
  { href: "/users", label: "Users", icon: Users, permission: "users.read" },
  { href: "/teams", label: "Teams", icon: UsersRound, permission: "users.read" },
  { href: "/roles", label: "Roles", icon: Shield, permission: "roles.manage" },
  { href: "/setup", label: "Pipeline setup", icon: SlidersHorizontal, permission: "crm.configure" },
  { href: "/routing", label: "Lead routing", icon: Route, permission: "crm.configure" },
  { href: "/settings", label: "Settings", icon: Settings, permission: "settings.manage" },
  { href: "/audit", label: "Audit log", icon: Activity, permission: "audit.read" },
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
        "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-muted-foreground hover:bg-accent hover:text-foreground",
        active && "bg-accent font-medium text-foreground",
      )}
    >
      <Icon className="size-4 opacity-80" />
      {item.label}
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
  if (!me) return null;
  const mainItems = MAIN.filter((i) => !i.permission || can(i.permission)).map((i) =>
    i.href === "/leads" ? { ...i, label: label("lead", true) } : i,
  );
  const workspaceItems = WORKSPACE.filter((i) => !i.permission || can(i.permission));
  // Typing an admin address directly gets a clear refusal (the backend refuses the data too).
  const locked = WORKSPACE.find((i) => path.startsWith(i.href) && i.permission && !can(i.permission));
  const close = () => setMenuOpen(false);

  const workspaceBadge = (
    <div className="flex min-w-0 items-center gap-2">
      <div className="grid size-6 shrink-0 place-items-center rounded-md bg-primary text-[11px] font-bold text-primary-foreground">
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
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-2 md:hidden">
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
          "fixed inset-y-0 left-0 z-50 flex w-64 shrink-0 flex-col gap-0.5 border-r bg-sidebar px-2 py-2.5 transition-transform md:static md:w-56 md:translate-x-0",
          menuOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="mb-2 flex items-center justify-between rounded-md px-2 py-1.5">
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
            <div className="flex items-center gap-1.5 px-2 pt-3 pb-1 text-[11px] text-muted-foreground">
              <Building2 className="size-3" /> Workspace
            </div>
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
      <main className="flex min-w-0 flex-1 flex-col overflow-auto">
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
export function PageHeader({ title, count, actions }: { title: string; count?: number; actions?: React.ReactNode }) {
  return (
    <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-2.5 gap-y-2 border-b px-4 py-2">
      <h1 className="text-sm font-semibold">{title}</h1>
      {count !== undefined ? <span className="text-muted-foreground">{count}</span> : null}
      {actions ? <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">{actions}</div> : null}
    </div>
  );
}
