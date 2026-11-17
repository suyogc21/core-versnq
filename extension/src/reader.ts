// Everything that reads WhatsApp Web lives in this one file. When WhatsApp changes its page,
// only this file needs fixing. It only reads; it never clicks, types or sends.

const READER = {
  main: "#main",
  title: "#main header span[title], #main header [dir='auto']",
  message: "#main [data-id]",
  meta: "[data-pre-plain-text]",
  text: "span.selectable-text",
  composer: "#main footer div[contenteditable='true']",
};

/** data-id used to be "true_919876543210@c.us_3EB0C0FFEE" (sent by me, chat, message id). Since
 * Nov 2026 WhatsApp Web shows only the message id ("3EB0C0FFEE"): then who sent it comes from the
 * bubble (outgoing style or the ticks only my messages have), and the chat from the header. */
function parseDataId(dataId: string, el?: Element): { fromMe: boolean; chatJid: string | null; msgId: string } | null {
  const m = /^(true|false)_([^_]+@[a-z.]+)_(.+)$/.exec(dataId);
  if (m) return { fromMe: m[1] === "true", chatJid: m[2], msgId: m[3] };
  if (!/^[A-Za-z0-9]{8,64}$/.test(dataId) || !el) return null;
  return { fromMe: sentByMe(el), chatJid: null, msgId: dataId };
}

function sentByMe(el: Element): boolean {
  if (el.closest(".message-out") || el.querySelector(".message-out")) return true;
  if (el.closest(".message-in") || el.querySelector(".message-in")) return false;
  return !!el.querySelector("[data-icon='msg-check'], [data-icon='msg-dblcheck'], [data-icon='msg-time'], [data-icon='msg-dblcheck-ack']");
}

function phoneFromJid(jid: string): string | null {
  const m = /^(\d{7,15})@(c\.us|s\.whatsapp\.net)$/.exec(jid);
  return m ? m[1] : null;
}

function phoneFromTitle(title: string): string | null {
  const digits = title.replace(/[^\d+]/g, "");
  return /^\+\d{7,15}$/.test(digits) ? digits.slice(1) : null;
}

/** "[10:32 am, 12/11/2026] Name: " → ISO time (day/month order from the browser's language). */
function parsePrePlain(pre: string | null, lang = navigator.language): string | undefined {
  if (!pre) return undefined;
  const m = /\[(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?,\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\]/i.exec(pre);
  if (!m) return undefined;
  let hour = Number(m[1]);
  const ampm = (m[3] || "").toLowerCase().replace(/\./g, "");
  if (ampm === "pm" && hour < 12) hour += 12;
  if (ampm === "am" && hour === 12) hour = 0;
  const monthFirst = lang.toLowerCase() === "en-us";
  const [a, b] = [Number(m[4]), Number(m[5])];
  const day = monthFirst ? b : a;
  const month = monthFirst ? a : b;
  const year = m[6].length === 2 ? 2000 + Number(m[6]) : Number(m[6]);
  const when = new Date(year, month - 1, day, hour, Number(m[2]));
  return Number.isNaN(when.getTime()) ? undefined : when.toISOString();
}

function kindOf(el: Element): WaMessage["kind"] {
  if (el.querySelector("[data-icon='audio-play'], [data-icon='ptt-status'], audio")) return "voice";
  if (el.querySelector("[data-icon^='document'], [data-icon='audio-file']")) return "document";
  if (el.querySelector("video, [data-icon='media-play']")) return "video";
  if (el.querySelector("img[src^='blob:']")) return "photo";
  if (el.querySelector("[data-testid='sticker'], img[alt='sticker']")) return "sticker";
  return el.querySelector(READER.text) ? "text" : "other";
}

/** The open chat and the messages WhatsApp Web currently shows for it. */
function readChat(doc: Document = document): ChatSnapshot {
  const main = doc.querySelector(READER.main);
  if (!main) return { chat: null, messages: [] };
  const titleEl = main.querySelector(READER.title.replace(/#main /g, ""));
  const title = (titleEl?.getAttribute("title") || titleEl?.textContent || "").trim();
  const rows = Array.from(doc.querySelectorAll(READER.message));
  let chatJid: string | null = null;
  const messages: WaMessage[] = [];
  for (const el of rows) {
    const parsed = parseDataId(el.getAttribute("data-id") || "", el);
    if (!parsed) continue;
    chatJid = chatJid || parsed.chatJid;
    const pre = el.querySelector(READER.meta)?.getAttribute("data-pre-plain-text") ?? null;
    const text = Array.from(el.querySelectorAll(READER.text))
      .map((t) => (t as HTMLElement).innerText || t.textContent || "")
      .join("\n")
      .trim();
    messages.push({ id: parsed.msgId, from_me: parsed.fromMe, text, kind: kindOf(el), at: parsePrePlain(pre) });
  }
  const isGroup = (!!chatJid && chatJid.endsWith("@g.us")) || !!main.querySelector("header [data-icon^='default-group']");
  const phone = (chatJid && phoneFromJid(chatJid)) || phoneFromTitle(title);
  return {
    chat: { key: chatJid || title, title, phone, is_group: isGroup },
    messages: isGroup ? [] : messages, // group chats are never read
  };
}

/** Puts text into WhatsApp's message box. The rep presses Send. */
function insertText(text: string, doc: Document = document): boolean {
  const box = doc.querySelector(READER.composer) as HTMLElement | null;
  if (!box) return false;
  box.focus();
  return doc.execCommand("insertText", false, text);
}
