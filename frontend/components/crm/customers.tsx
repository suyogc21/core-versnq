"use client";

import { BadgeCheck, Check, Download, FileText, Paperclip, Plus, Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { CustomFieldsEditor } from "@/components/crm/bits";
import { MoneyCard } from "@/components/crm/money";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth";
import { type FieldDef, fieldValue, relative, when } from "@/lib/crm";
import {
  type Customer,
  type CustomerDocument,
  DOC_STATUS,
  type StoredFile,
  fileUrl,
  formatBytes,
  uploadFile,
  useChecklist,
  useCustomerFields,
  useLeadCustomer,
  useRefreshCustomers,
} from "@/lib/customers";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

function Card({ title, action, children }: { title: React.ReactNode; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="surface space-y-3 p-4">
      <h4 className="flex items-center justify-between gap-2 text-[13px] font-semibold">
        {title}
        {action}
      </h4>
      {children}
    </section>
  );
}

export function MakeCustomerButton({ leadId, dealId, size = "sm" }: { leadId: string; dealId?: string; size?: "sm" | "default" }) {
  const label = useLabels();
  const refresh = useRefreshCustomers();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size={size}
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const c = unwrap(await api.POST("/api/v1/leads/{lead_id}/customer", { params: { path: { lead_id: leadId } }, body: { deal_id: dealId ?? null } }));
          toast.success(`Now ${label("customer").toLowerCase()} ${c.number}`);
          refresh();
        } catch (e) {
          toast.error((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <BadgeCheck /> Make {label("customer").toLowerCase()}
    </Button>
  );
}

/** Everything customer on the lead page: details, documents and the customer's link. */
export function CustomerSection({ leadId }: { leadId: string }) {
  const { can } = useAuth();
  const label = useLabels();
  const customer = useLeadCustomer(leadId, can("customers.read"));
  if (!can("customers.read") || customer.isLoading) return null;
  if (!customer.data) {
    if (!can("customers.create")) return null;
    return (
      <Card title={label("customer")}>
        <p className="text-xs text-muted-foreground">
          Not {label("customer").toLowerCase()} yet. Making them one keeps everything here and starts their document checklist.
        </p>
        <MakeCustomerButton leadId={leadId} />
      </Card>
    );
  }
  return (
    <>
      <CustomerCard customer={customer.data} />
      <MoneyCard customerId={customer.data.id} />
      <DocumentsCard customer={customer.data} />
    </>
  );
}

export function CustomerCard({ customer }: { customer: Customer }) {
  const { can } = useAuth();
  const label = useLabels();
  const fields = useCustomerFields();
  const refresh = useRefreshCustomers();
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const editable = can("leads.edit");
  const list = (fields.data ?? []) as FieldDef[];
  const custom = customer.custom_fields as Record<string, unknown>;
  async function patch(body: { status?: "active" | "inactive"; custom_fields?: Record<string, unknown> }) {
    try {
      unwrap(await api.PATCH("/api/v1/customers/{customer_id}", { params: { path: { customer_id: customer.id } }, body: { version: customer.version, ...body } }));
      refresh();
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  }
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {label("customer")}
          <span className="rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-700 tabular-nums dark:text-emerald-300">{customer.number}</span>
        </span>
      }
      action={
        editable && list.length > 0 ? (
          <button
            className="text-xs font-medium text-muted-foreground hover:text-foreground"
            onClick={() => {
              setValues(custom);
              setEditing(!editing);
            }}
          >
            {editing ? "Cancel" : "Edit"}
          </button>
        ) : undefined
      }
    >
      <dl className="grid grid-cols-[7rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 text-xs">
        <dt className="text-muted-foreground">Since</dt>
        <dd title={when(customer.since)}>{relative(customer.since)}</dd>
        <dt className="text-muted-foreground">Status</dt>
        <dd className="flex items-center gap-2">
          {editable ? (
            <Switch aria-label="Active customer" checked={customer.status === "active"} onCheckedChange={(on) => patch({ status: on ? "active" : "inactive" })} />
          ) : null}
          <span className={cn(customer.status !== "active" && "text-muted-foreground")}>{customer.status === "active" ? "Active" : "Inactive"}</span>
        </dd>
        {!editing &&
          list
            .filter((f) => f.type !== "calculated" || custom[f.key] != null)
            .map((f) => (
              <div key={f.key} className="contents">
                <dt className="text-muted-foreground">{f.label}</dt>
                <dd className="break-words">{fieldValue(f, custom[f.key])}</dd>
              </div>
            ))}
      </dl>
      {editing && (
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await patch({ custom_fields: values })) {
              setEditing(false);
              toast.success("Saved");
            }
          }}
        >
          <CustomFieldsEditor fields={list} values={values} onChange={setValues} />
          <Button size="sm" type="submit">
            Save
          </Button>
        </form>
      )}
    </Card>
  );
}

export function StatusPill({ status }: { status: string }) {
  const s = DOC_STATUS[status] ?? DOC_STATUS.pending;
  return <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap", s.tone)}>{s.label}</span>;
}

export function DocumentsCard({ customer }: { customer: Customer }) {
  const { can } = useAuth();
  const list = useChecklist(customer.id);
  const refresh = useRefreshCustomers();
  const [other, setOther] = useState<string | null>(null);
  const editable = can("leads.edit");
  const docs = list.data?.documents ?? [];
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Documents
          {list.data && list.data.required > 0 && (
            <span className="font-normal text-muted-foreground tabular-nums">
              {list.data.done} of {list.data.required} required
            </span>
          )}
        </span>
      }
    >
      {list.isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}
      {list.data && docs.length === 0 && (
        <p className="text-xs text-muted-foreground">No documents asked for. Admins set the checklist under Settings → Records and fields.</p>
      )}
      <ul className="space-y-2">
        {docs.map((d) => (
          <DocumentRow key={d.id} customerId={customer.id} doc={d} editable={editable} onChange={refresh} />
        ))}
      </ul>
      {editable &&
        (other === null ? (
          <button className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground" onClick={() => setOther("")}>
            <Plus className="size-3.5" /> Other document
          </button>
        ) : (
          <form
            className="flex gap-1.5"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                unwrap(await api.POST("/api/v1/customers/{customer_id}/documents", { params: { path: { customer_id: customer.id } }, body: { name: other } }));
                setOther(null);
                refresh();
              } catch (err) {
                toast.error((err as Error).message);
              }
            }}
          >
            <Input autoFocus aria-label="Document name" className="h-7 text-xs" placeholder="e.g. Bank statement" value={other} onChange={(e) => setOther(e.target.value)} />
            <Button size="sm" type="submit" disabled={!other.trim()}>
              Add
            </Button>
            <Button size="sm" variant="ghost" type="button" onClick={() => setOther(null)}>
              Cancel
            </Button>
          </form>
        ))}
    </Card>
  );
}

function DocumentRow({ customerId, doc, editable, onChange }: { customerId: string; doc: CustomerDocument; editable: boolean; onChange: () => void }) {
  const { can } = useAuth();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ file: StoredFile; url: string } | null>(null);
  const canReview = can("documents.verify") && doc.files.length > 0;
  const accept = doc.allow_office ? "image/*,application/pdf,.doc,.docx,.xls,.xlsx" : "image/*,application/pdf";

  async function send(files: FileList | File[]) {
    setBusy(true);
    try {
      for (const f of Array.from(files)) await uploadFile(customerId, doc.id, f);
      toast.success(`${doc.name}: uploaded`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
      onChange();
    }
  }
  async function review(verified: boolean, reason?: string) {
    try {
      const path = { customer_id: customerId, document_id: doc.id };
      if (verified) unwrap(await api.POST("/api/v1/customers/{customer_id}/documents/{document_id}/verify", { params: { path } }));
      else unwrap(await api.POST("/api/v1/customers/{customer_id}/documents/{document_id}/reject", { params: { path }, body: { reason: reason ?? "" } }));
      setRejecting(null);
      onChange();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function open(file: StoredFile, download = false) {
    try {
      const url = await fileUrl(customerId, file.id, download);
      if (download || !file.previewable) {
        const a = document.createElement("a");
        a.href = url;
        a.download = file.original_name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
      } else setPreview({ file, url });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <li
      data-doc={doc.name}
      className={cn("rounded-lg border bg-card p-2.5 transition-colors", over && "border-primary bg-primary/5")}
      onDragOver={(e) => {
        if (!editable) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (editable && e.dataTransfer.files.length) send(e.dataTransfer.files);
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <FileText className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium" title={doc.hint ?? undefined}>
          {doc.name}
          {doc.is_required && <span className="text-destructive"> *</span>}
        </span>
        <StatusPill status={doc.status} />
      </div>
      {doc.hint && doc.status === "pending" && <p className="mt-1 pl-6 text-[11px] text-muted-foreground">{doc.hint}</p>}
      {doc.status === "rejected" && doc.reject_reason && <p className="mt-1 pl-6 text-[11px] text-destructive">Rejected: {doc.reject_reason}</p>}
      {doc.status === "verified" && doc.reviewed_by_name && (
        <p className="mt-1 pl-6 text-[11px] text-muted-foreground">
          Verified by {doc.reviewed_by_name} · {relative(doc.reviewed_at)}
        </p>
      )}
      {doc.files.length > 0 && (
        <ul className="mt-1.5 space-y-1 pl-6">
          {doc.files.map((f) => (
            <li key={f.id} className="group flex items-center gap-1.5 text-xs">
              <Paperclip className="size-3 shrink-0 text-muted-foreground" />
              <button className="min-w-0 truncate text-left hover:underline" onClick={() => open(f)}>
                {f.original_name}
              </button>
              <span className="shrink-0 text-muted-foreground">
                {formatBytes(f.size_bytes)}
              </span>
              <button aria-label={`Download ${f.original_name}`} className="ml-auto p-0.5 text-muted-foreground hover:text-foreground" onClick={() => open(f, true)}>
                <Download className="size-3.5" />
              </button>
              {can("leads.delete") && (
                <button
                  aria-label={`Delete ${f.original_name}`}
                  className="p-0.5 text-muted-foreground hover:text-destructive"
                  onClick={async () => {
                    if (!window.confirm(`Delete ${f.original_name}? This cannot be undone.`)) return;
                    try {
                      unwrap(await api.DELETE("/api/v1/customers/{customer_id}/files/{file_id}", { params: { path: { customer_id: customerId, file_id: f.id } } }));
                      onChange();
                    } catch (e) {
                      toast.error((e as Error).message);
                    }
                  }}
                >
                  <Trash2 className="size-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {(editable || canReview) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-6">
          {editable && (
            <>
              <input ref={input} type="file" multiple accept={accept} className="hidden" aria-label={`Upload ${doc.name}`} onChange={(e) => e.target.files?.length && send(e.target.files)} />
              <Button size="xs" variant="outline" disabled={busy} onClick={() => input.current?.click()}>
                <Upload /> {busy ? "Uploading…" : "Upload"}
              </Button>
            </>
          )}
          {canReview && doc.status !== "verified" && (
            <Button size="xs" variant="outline" onClick={() => review(true)}>
              <Check /> Verify
            </Button>
          )}
          {canReview && doc.status !== "rejected" && rejecting === null && (
            <Button size="xs" variant="ghost" onClick={() => setRejecting("")}>
              <X /> Reject
            </Button>
          )}
        </div>
      )}
      {rejecting !== null && (
        <form
          className="mt-2 flex gap-1.5 pl-6"
          onSubmit={(e) => {
            e.preventDefault();
            review(false, rejecting);
          }}
        >
          <Input autoFocus aria-label="Why is it rejected?" className="h-7 text-xs" placeholder="Why? e.g. Photo is blurry" value={rejecting} onChange={(e) => setRejecting(e.target.value)} />
          <Button size="sm" type="submit" disabled={!rejecting.trim()}>
            Reject
          </Button>
          <Button size="sm" variant="ghost" type="button" onClick={() => setRejecting(null)}>
            Cancel
          </Button>
        </form>
      )}
      {preview && (
        <Dialog
          open
          onOpenChange={(o) => {
            if (!o) {
              URL.revokeObjectURL(preview.url);
              setPreview(null);
            }
          }}
        >
          <DialogContent className="sm:max-w-3xl">
            <DialogHeader>
              <DialogTitle className="truncate">{preview.file.original_name}</DialogTitle>
            </DialogHeader>
            {preview.file.content_type === "application/pdf" ? (
              <iframe title={preview.file.original_name} src={preview.url} className="h-[70vh] w-full rounded-md border" />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element -- a private file shown from a temporary browser URL
              <img alt={preview.file.original_name} src={preview.url} className="max-h-[70vh] w-full rounded-md object-contain" />
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => open(preview.file, true)}>
                <Download /> Download
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </li>
  );
}
