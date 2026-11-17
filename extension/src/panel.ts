// The side panel beside WhatsApp Web. Everything shown is built with textContent (never
// innerHTML), so a name or message can't inject anything into the panel.

const app = document.getElementById("app") as HTMLElement;
const who = document.getElementById("who") as HTMLElement;
let current: PanelState | null = null;
let busy = false;
let note = "";

type Child = Node | string | null | false | undefined;
function h(tag: string, attrs: Record<string, any> = {}, ...children: Child[]): HTMLElement {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, String(v));
  }
  for (const c of children) if (c) el.append(c instanceof Node ? c : document.createTextNode(c));
  return el;
}

async function ask<T = any>(msg: Record<string, unknown>): Promise<T> {
  const r = await chrome.runtime.sendMessage(msg);
  if (!r?.ok) throw new Error(r?.error || "Something went wrong");
  return r.data as T;
}

function money(list: { currency: string; amount_minor?: number; due_minor?: number }[]): string {
  return list
    .map((x) =>
      new Intl.NumberFormat(undefined, { style: "currency", currency: x.currency, maximumFractionDigits: 0 }).format(
        (x.amount_minor ?? x.due_minor ?? 0) / 100,
      ),
    )
    .join(" + ");
}

async function act(fn: () => Promise<unknown>, after?: () => void): Promise<void> {
  busy = true;
  render();
  try {
    const out = await fn();
    if (out && typeof out === "object" && "connected" in (out as object)) current = out as PanelState;
    after?.();
  } catch (e) {
    if (current) current.error = (e as Error).message;
  } finally {
    busy = false;
    render();
  }
}

function connectView(): HTMLElement {
  const base = h("input", { placeholder: "yourcompany.core.versnq.in", id: "base", "aria-label": "Workspace address" }) as HTMLInputElement;
  const code = h("input", { placeholder: "1234-5678", id: "code", inputmode: "numeric", "aria-label": "Connect code" }) as HTMLInputElement;
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Connect to Versnq Core"),
    h("p", { class: "muted" }, "In Versnq Core open My account → WhatsApp extension → Connect the extension, then enter the code here."),
    h("label", {}, "Workspace address", base),
    h("label", {}, "Code", code),
    h(
      "button",
      {
        class: "primary",
        disabled: busy,
        onclick: () =>
          act(async () => {
            let origin = base.value.trim();
            if (!/^https?:\/\//.test(origin)) origin = (origin.includes("localhost") ? "http://" : "https://") + origin;
            origin = new URL(origin).origin;
            const granted = await chrome.permissions.request({ origins: [`${origin}/*`] }); // only this address
            if (!granted) throw new Error("Allow the extension to reach your workspace to continue");
            return ask({ type: "connect", base: origin, code: code.value, device: navigator.userAgent.includes("Edg/") ? "Edge" : "Chrome" });
          }),
      },
      "Connect",
    ),
  );
}

function leadView(s: PanelState, lead: LeadCard): HTMLElement {
  const noteBox = h("textarea", { rows: 2, placeholder: "Add a note to the lead…", "aria-label": "Note" }) as HTMLTextAreaElement;
  noteBox.value = note;
  noteBox.addEventListener("input", () => (note = noteBox.value));
  const when = h("input", { type: "datetime-local", "aria-label": "Next follow-up" }) as HTMLInputElement;
  return h(
    "div",
    { class: "card", "data-lead": lead.name },
    h("div", { class: "row" }, h("h2", {}, lead.name), lead.is_yours ? h("span", { class: "ok" }, "· yours") : null),
    lead.org_name ? h("div", { class: "muted" }, lead.org_name) : null,
    h(
      "dl",
      {},
      h("dt", {}, "Stage"),
      h("dd", {}, lead.stage),
      h("dt", {}, "Owner"),
      h("dd", {}, lead.owner_name ?? "Unassigned"),
      h("dt", {}, "Next follow-up"),
      h("dd", {}, lead.next_follow_up_at ? new Date(lead.next_follow_up_at).toLocaleString() : "—"),
      h("dt", {}, "Open deals"),
      h("dd", {}, lead.open_deals ? `${lead.open_deals}${lead.open_deal_value.length ? ` · ${money(lead.open_deal_value)}` : ""}` : "None"),
      lead.balance_due.length ? h("dt", {}, "Balance due") : null,
      lead.balance_due.length ? h("dd", {}, money(lead.balance_due)) : null,
    ),
    h("div", { class: "muted" }, s.logged ? `${s.logged} message${s.logged === 1 ? "" : "s"} saved to Core from this chat` : "Chat messages are saved to Core automatically."),
    h("div", { class: "row" }, h("a", { href: lead.url, target: "_blank", rel: "noopener" }, "Open in Versnq"), h("button", { disabled: busy, onclick: () => act(() => ask({ type: "sync" })) }, "Sync this chat")),
    noteBox,
    h("button", { disabled: busy, onclick: () => note.trim() && act(() => ask({ type: "note", body: note.trim() }), () => (note = "")) }, "Add note"),
    h("label", {}, "Next follow-up", when),
    h("button", { disabled: busy, onclick: () => when.value && act(() => ask({ type: "follow_up", at: new Date(when.value).toISOString() })) }, "Set follow-up"),
  );
}

function unknownView(s: PanelState): HTMLElement {
  const name = h("input", { "aria-label": "Lead name" }) as HTMLInputElement;
  name.value = s.chat?.title ?? "";
  const q = h("input", { placeholder: "Search leads…", "aria-label": "Search leads" }) as HTMLInputElement;
  const results = h("div", { class: "list" });
  q.addEventListener("input", async () => {
    if (q.value.trim().length < 2) return results.replaceChildren();
    const hits = await ask<{ id: string; name: string; phone: string | null }[]>({ type: "search", q: q.value.trim() }).catch(() => []);
    results.replaceChildren(...hits.map((x) => h("button", { onclick: () => act(() => ask({ type: "link", lead_id: x.id })) }, `${x.name}${x.phone ? ` · ${x.phone}` : ""}`)));
  });
  return h(
    "div",
    { class: "card" },
    h("h2", {}, "Not a lead yet"),
    h("p", { class: "muted" }, s.phone ? `${s.phone} isn't in Versnq Core (or isn't yours to see).` : "WhatsApp Web doesn't show this chat's number."),
    h("label", {}, "Name", name),
    h("button", { class: "primary", disabled: busy || !name.value, onclick: () => act(() => ask({ type: "create", name: name.value.trim() })) }, "Create lead"),
    h("p", { class: "muted" }, "Or link this chat to an existing lead:"),
    q,
    results,
  );
}

function repliesView(): HTMLElement {
  const box = h("div", { class: "list" });
  const load = h(
    "button",
    {
      onclick: async () => {
        const list = await ask<{ id: string; name: string; body: string }[]>({ type: "replies" }).catch(() => []);
        box.replaceChildren(
          ...(list.length
            ? list.map((r) => h("button", { title: r.body, onclick: () => act(() => ask({ type: "insert", text: r.body })) }, r.name))
            : [h("span", { class: "muted" }, "No saved replies yet. Add them in Versnq Core's inbox.")]),
        );
      },
    },
    "Saved replies",
  );
  return h("div", { class: "card" }, h("div", { class: "row" }, load, h("span", { class: "muted" }, "Puts the text in WhatsApp; you press Send.")), box);
}

function render(): void {
  const s = current;
  if (!s) return;
  who.textContent = s.connected ? `${s.user_name ?? ""} · ${s.workspace ?? ""}` : "";
  const parts: Child[] = [];
  if (!s.connected) parts.push(connectView());
  else if (!s.chat) parts.push(h("p", { class: "muted" }, "Open a chat in WhatsApp Web."));
  else if (s.chat.is_group) parts.push(h("p", { class: "muted" }, "Group chats aren't read by the extension."));
  else if (s.lead) parts.push(leadView(s, s.lead), repliesView());
  else parts.push(unknownView(s));
  if (s.error) parts.push(h("p", { class: "error", role: "alert" }, s.error));
  if (s.connected) parts.push(h("button", { onclick: () => act(() => ask({ type: "disconnect" })) }, "Disconnect this browser"));
  app.replaceChildren(...(parts.filter(Boolean) as Node[]));
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "update" && !busy) {
    current = msg.state;
    render();
  }
  return false;
});

ask<PanelState>({ type: "state" })
  .then((s) => {
    current = s;
    render();
    return ask({ type: "sync" }).catch(() => undefined);
  })
  .catch((e) => (app.textContent = (e as Error).message));
