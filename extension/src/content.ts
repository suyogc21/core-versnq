// Runs inside WhatsApp Web. Watches the open chat (with reader.ts) and hands it to the
// extension's background, which decides what reaches Core. Never sends a WhatsApp message.

let lastSignature = "";
let timer: number | undefined;

function signature(s: ChatSnapshot): string {
  const last = s.messages[s.messages.length - 1];
  return `${s.chat?.key ?? ""}|${s.messages.length}|${last?.id ?? ""}`;
}

function report(force = false): void {
  const snap = readChat();
  const sig = signature(snap);
  if (!force && sig === lastSignature) return;
  lastSignature = sig;
  chrome.runtime.sendMessage({ type: "snapshot", snapshot: snap, force }).catch(() => undefined);
}

new MutationObserver(() => {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => report(), 1500); // calm: at most every 1.5 s
}).observe(document.body, { childList: true, subtree: true });

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.type === "insert") {
    reply({ ok: insertText(String(msg.text ?? "")) });
  } else if (msg?.type === "sync") {
    report(true);
    reply({ ok: true });
  }
  return false;
});

report();
