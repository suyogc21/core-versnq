"use client";

import { Activity, Building2, LogOut, Moon, Settings, Shield, Sun, Sunrise, Users, UsersRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";

import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { useWorkspaceSettings } from "@/lib/settings";

type NavItem = { href: string; label: string; icon: typeof Users; permission?: string };

const MAIN: NavItem[] = [{ href: "/", label: "My Day", icon: Sunrise }];
const WORKSPACE: NavItem[] = [
  { href: "/users", label: "Users", icon: Users, permission: "users.read" },
  { href: "/teams", label: "Teams", icon: UsersRound, permission: "users.read" },
  { href: "/roles", label: "Roles", icon: Shield, permission: "roles.manage" },
  { href: "/settings", label: "Settings", icon: Settings, permission: "settings.manage" },
  { href: "/audit", label: "Audit log", icon: Activity, permission: "audit.read" },
];

function initials(name: string) {
  return name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
}

function NavLink({ item }: { item: NavItem }) {
  const path = usePathname();
  const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
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
  const { resolvedTheme, setTheme } = useTheme();
  useWorkspaceSettings(); // loads labels and applies the workspace colour
  if (!me) return null;
  const workspaceItems = WORKSPACE.filter((i) => !i.permission || can(i.permission));

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-56 shrink-0 flex-col gap-0.5 border-r bg-sidebar px-2 py-2.5">
        <div className="mb-2 flex items-center gap-2 rounded-md px-2 py-1.5">
          <div className="grid size-6 place-items-center rounded-md bg-primary text-[11px] font-bold text-primary-foreground">
            {me.tenant.name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="truncate font-semibold">{me.tenant.name}</div>
            <div className="truncate text-[11px] text-muted-foreground">{me.tenant.slug}</div>
          </div>
        </div>
        {MAIN.map((i) => (
          <NavLink key={i.href} item={i} />
        ))}
        {workspaceItems.length > 0 && (
          <>
            <div className="flex items-center gap-1.5 px-2 pt-3 pb-1 text-[11px] text-muted-foreground">
              <Building2 className="size-3" /> Workspace
            </div>
            {workspaceItems.map((i) => (
              <NavLink key={i.href} item={i} />
            ))}
          </>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-2 border-t px-2 pt-2.5">
          <div className="grid size-6 place-items-center rounded-full bg-primary/15 text-[10px] font-semibold text-foreground">
            {initials(me.name)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{me.name}</div>
            <div className="truncate text-[11px] text-muted-foreground">{me.role.name}</div>
          </div>
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
      <main className="flex min-w-0 flex-1 flex-col overflow-auto">{children}</main>
    </div>
  );
}

/** Page title bar, matching the mockup's top bar. */
export function PageHeader({ title, count, actions }: { title: string; count?: number; actions?: React.ReactNode }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2.5 border-b px-4">
      <h1 className="text-sm font-semibold">{title}</h1>
      {count !== undefined ? <span className="text-muted-foreground">{count}</span> : null}
      <div className="ml-auto flex items-center gap-2">{actions}</div>
    </div>
  );
}
