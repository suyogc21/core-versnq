"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useRouter } from "next/navigation";

import { Popover, PopoverHeading } from "@/components/data-table/popover";
import { api } from "@/lib/api/client";
import { type NotificationItem, relative, useNotifications } from "@/lib/crm";
import { cn } from "@/lib/utils";

/** In-app notifications: new leads, re-enquiries, due tasks, missed response times. */
export function NotificationBell() {
  const qc = useQueryClient();
  const router = useRouter();
  const list = useNotifications();
  const items = list.data?.items ?? [];
  const unread = list.data?.unread ?? 0;

  async function markRead(ids?: string[]) {
    await api.POST("/api/v1/notifications/read", { body: { ids: ids ?? null } });
    qc.invalidateQueries({ queryKey: ["notifications"] });
  }

  function open(n: NotificationItem, close: () => void) {
    close();
    if (!n.read_at) markRead([n.id]);
    if (n.lead_id) router.push(`/leads/${n.lead_id}`);
  }

  return (
    <Popover
      align="end"
      className="w-80 max-w-[calc(100vw-2rem)]"
      trigger={({ toggle }) => (
        <button
          type="button"
          onClick={toggle}
          aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
          className="relative rounded p-1.5 text-muted-foreground hover:bg-accent"
        >
          <Bell className="size-4" />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 grid min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      )}
    >
      {(close) => (
        <>
          <div className="flex items-center justify-between">
            <PopoverHeading>Notifications</PopoverHeading>
            {unread > 0 && (
              <button className="px-2 text-[11px] text-primary hover:underline" onClick={() => markRead()}>
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 && <p className="px-2 py-4 text-center text-xs text-muted-foreground">Nothing yet.</p>}
          {items.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => open(n, close)}
              className={cn("flex w-full gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent", !n.read_at && "bg-primary/5")}
            >
              <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-primary")} />
              <span className="min-w-0 flex-1">
                <span className="block text-xs leading-snug">{n.title}</span>
                <span className="text-[11px] text-muted-foreground">{relative(n.created_at)}</span>
              </span>
            </button>
          ))}
        </>
      )}
    </Popover>
  );
}
