"use client";

import { Mail, MessageCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { relative } from "@/lib/crm";
import { useLeadConversations, useRefreshInbox } from "@/lib/inbox";
import { useModuleOn } from "@/lib/modules";
import { type WaTemplate, useWaTemplates } from "@/lib/whatsapp";

/** The lead's conversations (email, and WhatsApp logged by the extension, step 10a) and a new
 * email from the CRM (step 9b). WhatsApp itself opens from the header's WhatsApp button. */
export function LeadEmails({ leadId, email, name }: { leadId: string; email: string | null; name: string }) {
  const { can } = useAuth();
  const list = useLeadConversations(leadId);
  const [writing, setWriting] = useState(false);
  const [templating, setTemplating] = useState(false);
  const waOn = useModuleOn("whatsapp_number");
  const wa = useWaTemplates(can("inbox.reply") && waOn);
  const approved = (wa.data ?? []).filter((t) => t.status === "approved");
  if (!can("inbox.reply")) return null;
  return (
    <div className="space-y-2 text-xs" data-lead-emails>
      {(list.data ?? []).length === 0 && <p className="text-muted-foreground">No emails or WhatsApp messages yet.</p>}
      {(list.data ?? []).slice(0, 5).map((r) => (
        <Link key={r.id} href={`/inbox?c=${r.id}`} className="block rounded-md px-1 py-1 hover:bg-muted/50">
          <div className="flex items-center gap-1.5">
            {r.channel === "whatsapp" ? <MessageCircle className="size-3 shrink-0 text-emerald-600" aria-label="WhatsApp" /> : <Mail className="size-3 shrink-0 text-muted-foreground" aria-label="Email" />}
            <span className="min-w-0 flex-1 truncate font-medium">{r.subject || "(no subject)"}</span>
            {r.waiting && <span className="shrink-0 text-amber-700 dark:text-amber-300">waiting</span>}
          </div>
          <div className="truncate text-muted-foreground">
            {relative(r.last_message_at)} · {r.snippet}
          </div>
        </Link>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={!email} title={email ? undefined : "Add an email address first"} onClick={() => setWriting(true)}>
          <Mail /> New email
        </Button>
        {waOn && approved.length > 0 && (
          <Button size="sm" variant="outline" onClick={() => setTemplating(true)} data-company-wa>
            <MessageCircle /> Company WhatsApp
          </Button>
        )}
      </div>
      {templating && <CompanyWhatsApp leadId={leadId} name={name} templates={approved} onClose={() => setTemplating(false)} />}
      {writing && <NewEmail leadId={leadId} name={name} email={email!} onClose={() => setWriting(false)} />}
    </div>
  );
}

function NewEmail({ leadId, name, email, onClose }: { leadId: string; name: string; email: string; onClose: () => void }) {
  const refresh = useRefreshInbox();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [cc, setCc] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            Email {name} <span className="text-sm font-normal text-muted-foreground">({email})</span>
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="space-y-1">
            <Label htmlFor="ne-cc">Cc</Label>
            <Input id="ne-cc" placeholder="Comma separated (optional)" value={cc} onChange={(e) => setCc(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ne-subject">Subject</Label>
            <Input id="ne-subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ne-body">Message</Label>
            <Textarea id="ne-body" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!subject.trim() || !body.trim() || busy}
            onClick={async () => {
              setBusy(true);
              try {
                unwrap(
                  await api.POST("/api/v1/leads/{lead_id}/emails", {
                    params: { path: { lead_id: leadId } },
                    body: { subject, body, cc: cc.split(",").map((x) => x.trim()).filter(Boolean) },
                  }),
                );
                toast.success("Sent");
                refresh();
                onClose();
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Send
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Send an approved template from the company's WhatsApp number (step 10b). */
function CompanyWhatsApp({ leadId, name, templates, onClose }: { leadId: string; name: string; templates: WaTemplate[]; onClose: () => void }) {
  const refresh = useRefreshInbox();
  const [id, setId] = useState(templates[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const tpl = templates.find((t) => t.id === id);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>WhatsApp {name} from the company number</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          WhatsApp lets a business start a chat only with an approved template. Once they answer, you can write freely for 24 hours from the inbox.
        </p>
        <div className="space-y-1.5">
          <Label htmlFor="cw-tpl">Template</Label>
          <select id="cw-tpl" className="h-9 w-full rounded-md border bg-transparent px-2 text-sm" value={id} onChange={(e) => setId(e.target.value)}>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
                {t.category === "marketing" ? " (marketing: opted-in people only)" : ""}
              </option>
            ))}
          </select>
        </div>
        {tpl && <p className="rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">{tpl.body}</p>}
        <DialogFooter>
          <Button
            disabled={!id || busy}
            onClick={async () => {
              setBusy(true);
              try {
                unwrap(await api.POST("/api/v1/leads/{lead_id}/whatsapp", { params: { path: { lead_id: leadId } }, body: { template_id: id } }));
                toast.success("Sent on WhatsApp");
                refresh();
                onClose();
              } catch (e) {
                toast.error((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Send
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
