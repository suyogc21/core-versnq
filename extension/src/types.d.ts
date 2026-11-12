// Shared shapes, and the small part of the Chrome extension API we use (no @types/chrome).

/** One message as read from WhatsApp Web. */
interface WaMessage {
  id: string; // WhatsApp's own id: nothing is logged twice
  from_me: boolean;
  text: string;
  kind: "text" | "photo" | "video" | "document" | "voice" | "sticker" | "other";
  at?: string; // ISO time, when WhatsApp Web shows it
}

/** The open chat. */
interface WaChat {
  key: string; // stable per chat: WhatsApp's chat id, else the chat's title
  title: string;
  phone: string | null; // digits with country code, when WhatsApp Web exposes it
  is_group: boolean;
}

interface ChatSnapshot {
  chat: WaChat | null;
  messages: WaMessage[];
}

interface LeadCard {
  id: string;
  name: string;
  org_name: string | null;
  stage: string;
  owner_name: string | null;
  is_yours: boolean;
  next_follow_up_at: string | null;
  open_deals: number;
  open_deal_value: { currency: string; amount_minor: number }[];
  balance_due: { currency: string; due_minor: number }[];
  url: string;
}

/** What the side panel shows. */
interface PanelState {
  connected: boolean;
  workspace: string | null;
  user_name: string | null;
  chat: WaChat | null;
  lead: LeadCard | null;
  phone: string | null; // cleaned by Core
  logged: number; // messages logged for this chat in this session
  error: string | null;
}

declare const chrome: {
  runtime: {
    sendMessage(msg: unknown): Promise<any>;
    onMessage: { addListener(cb: (msg: any, sender: any, reply: (r: unknown) => void) => boolean | void): void };
    getManifest(): { version: string };
  };
  storage: { local: { get(keys: string[]): Promise<Record<string, any>>; set(items: Record<string, unknown>): Promise<void>; remove(keys: string[]): Promise<void> } };
  tabs: {
    query(q: { url?: string; active?: boolean }): Promise<{ id?: number }[]>;
    sendMessage(tabId: number, msg: unknown): Promise<any>;
  };
  permissions: { request(p: { origins: string[] }): Promise<boolean> };
  sidePanel: { setPanelBehavior(o: { openPanelOnActionClick: boolean }): Promise<void> };
};
