// The extension's background: holds the sign-in, talks to Core, and decides what is logged.
// Only chats with a known lead are sent to Core; for any other chat only "is this a lead?"
// is asked (Core does not store the number). Nothing here sends a WhatsApp message.

const VERSION = chrome.runtime.getManifest().version;
const LOOKUP_TTL_MS = 60_000;

const state: PanelState = {
  connected: false,
  workspace: null,
  user_name: null,
  chat: null,
  lead: null,
  phone: null,
  logged: 0,
  error: null,
};
let lastSnapshot: ChatSnapshot = { chat: null, messages: [] };
const lookups = new Map<string, { at: number; lead: LeadCard | null; phone: string | null }>();
const sent = new Map<string, Set<string>>(); // chat key → message ids already handed to Core

async function settings(): Promise<{ base?: string; token?: string; workspace?: string; user_name?: string }> {
  return chrome.storage.local.get(["base", "token", "workspace", "user_name"]);
}

function push(): void {
  chrome.runtime.sendMessage({ type: "update", state }).catch(() => undefined); // panel may be closed
}

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const { base, token } = await settings();
  if (!base || !token) throw new ApiError(401, "Not connected");
  const res = await fetch(`${base}${path}`, {
    method: init.method ?? "GET",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", "X-Versnq-Extension": VERSION },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (res.status === 401) {
    await chrome.storage.local.remove(["token"]);
    state.connected = false;
    throw new ApiError(401, "Disconnected from Versnq. Connect again with a new code.");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, (data && (data.detail?.message || data.detail)) || `Error ${res.status}`);
  return data as T;
}

async function lookup(chat: WaChat, force: boolean): Promise<void> {
  const hit = lookups.get(chat.key);
  if (!force && hit && Date.now() - hit.at < LOOKUP_TTL_MS) {
    state.lead = hit.lead;
    state.phone = hit.phone;
    return;
  }
  const q = new URLSearchParams();
  if (chat.phone) q.set("phone", chat.phone);
  q.set("chat_key", chat.key);
  const out = await call<{ lead: LeadCard | null; phone: string | null }>(`/api/v1/extension/lookup?${q}`);
  lookups.set(chat.key, { at: Date.now(), lead: out.lead, phone: out.phone });
  state.lead = out.lead;
  state.phone = out.phone;
}

async function logNew(chat: WaChat, messages: WaMessage[]): Promise<void> {
  if (!state.lead) return;
  const done = sent.get(chat.key) ?? new Set<string>();
  const fresh = messages.filter((m) => !done.has(m.id));
  for (let i = 0; i < fresh.length; i += 200) {
    const batch = fresh.slice(i, i + 200);
    const out = await call<{ logged: number }>("/api/v1/extension/messages", {
      method: "POST",
      body: { lead_id: state.lead.id, messages: batch },
    });
    batch.forEach((m) => done.add(m.id));
    state.logged += out.logged;
  }
  sent.set(chat.key, done);
}

async function onSnapshot(snap: ChatSnapshot, force: boolean): Promise<void> {
  const changed = snap.chat?.key !== state.chat?.key;
  lastSnapshot = snap;
  state.chat = snap.chat;
  if (changed) {
    state.lead = null;
    state.phone = null;
    state.logged = 0;
  }
  state.error = null;
  const { token } = await settings();
  state.connected = !!token;
  if (!snap.chat || snap.chat.is_group || !token) return push();
  try {
    await lookup(snap.chat, force);
    await logNew(snap.chat, snap.messages);
  } catch (e) {
    state.error = (e as Error).message;
  }
  push();
}

async function whatsappTab(): Promise<number | undefined> {
  const tabs = await chrome.tabs.query({ url: "https://web.whatsapp.com/*" });
  return tabs[0]?.id;
}

async function refreshLead(out: { lead: LeadCard | null; phone: string | null }): Promise<PanelState> {
  if (state.chat) lookups.set(state.chat.key, { at: Date.now(), lead: out.lead, phone: out.phone ?? state.phone });
  state.lead = out.lead;
  if (state.lead && state.chat) await logNew(state.chat, lastSnapshot.messages); // log the chat now
  return state;
}

async function handle(msg: any): Promise<unknown> {
  switch (msg?.type) {
    case "snapshot":
      await onSnapshot(msg.snapshot, !!msg.force);
      return { ok: true };
    case "state": {
      const s = await settings();
      state.connected = !!s.token;
      state.workspace = s.workspace ?? null;
      state.user_name = s.user_name ?? null;
      return state;
    }
    case "connect": {
      const base = String(msg.base).replace(/\/+$/, "");
      const res = await fetch(`${base}/api/v1/extension/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: msg.code, device: msg.device }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new ApiError(res.status, data?.detail?.message || data?.detail || "Could not connect");
      await chrome.storage.local.set({ base, token: data.token, workspace: data.workspace, user_name: data.user_name });
      Object.assign(state, { connected: true, workspace: data.workspace, user_name: data.user_name, error: null });
      lookups.clear();
      if (lastSnapshot.chat) await onSnapshot(lastSnapshot, true);
      return state;
    }
    case "disconnect":
      await call("/api/v1/extension/disconnect", { method: "POST" }).catch(() => undefined);
      await chrome.storage.local.remove(["token", "user_name", "workspace"]);
      Object.assign(state, { connected: false, lead: null, user_name: null, workspace: null });
      return state;
    case "create":
      return refreshLead(
        await call("/api/v1/extension/leads", {
          method: "POST",
          body: { phone: state.chat?.phone ?? null, chat_key: state.chat?.key ?? null, name: msg.name },
        }),
      );
    case "search":
      return call(`/api/v1/extension/search?q=${encodeURIComponent(msg.q)}`);
    case "link":
      return refreshLead(await call("/api/v1/extension/link", { method: "POST", body: { chat_key: state.chat?.key, lead_id: msg.lead_id } }));
    case "note":
      return refreshLead(await call(`/api/v1/extension/leads/${state.lead?.id}/note`, { method: "POST", body: { body: msg.body } }));
    case "follow_up":
      return refreshLead(await call(`/api/v1/extension/leads/${state.lead?.id}/follow-up`, { method: "PUT", body: { at: msg.at } }));
    case "replies":
      return call("/api/v1/extension/replies");
    case "insert":
    case "sync": {
      const tab = await whatsappTab();
      if (tab === undefined) throw new ApiError(0, "Open WhatsApp Web first");
      return chrome.tabs.sendMessage(tab, msg);
    }
  }
  return null;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === "update") return false; // our own broadcast
  handle(msg)
    .then((r) => reply({ ok: true, data: r }))
    .catch((e: Error) => reply({ ok: false, error: e.message }));
  return true; // answer comes later
});

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => undefined);
