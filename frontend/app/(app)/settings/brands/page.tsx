"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { Brand } from "@/lib/brands";
import { useEntities, useMoneyOn } from "@/lib/money";

/** Settings → Brands (finish plan, batch 4): a company that runs several brands gives each its
 * name, colour, logo and billing entity, picks the default, and says which inboxes and which
 * WhatsApp number belong to which brand. With one brand or none, nothing else in Core changes. */
export default function BrandsPage() {
  const qc = useQueryClient();
  const brands = useQuery({
    queryKey: ["brands", "all"],
    queryFn: async () => unwrap(await api.GET("/api/v1/brands", { params: { query: { include_inactive: true } } })),
  });
  const [editing, setEditing] = useState<Brand | "new" | null>(null);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["brands"] });
    qc.invalidateQueries({ queryKey: ["brand-channels"] });
  }

  async function makeDefault(b: Brand) {
    try {
      unwrap(await api.POST("/api/v1/brands/{brand_id}/default", { params: { path: { brand_id: b.id } } }));
      refresh();
      toast.success(`${b.name} is now the default brand`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const list = brands.data ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        back={{ href: "/settings", label: "Settings" }}
        title="Brands"
        count={list.length}
        actions={
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus /> New brand
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-2xl space-y-6 p-4 sm:p-6">
          <p className="text-sm text-muted-foreground">
            Run several brands from one company. Each lead, deal and invoice belongs to a brand. New leads get the brand of the form, inbox or WhatsApp number they came
            in through, or the default one. In Settings → Users you can limit a person to some brands; they then see only those brands&apos; records.
          </p>
          {brands.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : list.length === 0 ? (
            <p className="surface p-6 text-center text-sm text-muted-foreground">No brands yet. With one brand or none, Core works as a single brand.</p>
          ) : (
            <ul className="surface divide-y text-sm">
              {list.map((b) => (
                <li key={b.id} className="flex flex-wrap items-center gap-2 p-3">
                  <span className="size-3 shrink-0 rounded-full border" style={{ background: b.colour ?? "transparent" }} aria-hidden />
                  <span className="font-medium">{b.name}</span>
                  {b.is_default && <Badge variant="secondary">Default</Badge>}
                  {!b.is_active && <Badge variant="outline">Off</Badge>}
                  <span className="ml-auto flex gap-1">
                    {b.is_active && !b.is_default && (
                      <Button size="sm" variant="ghost" onClick={() => makeDefault(b)}>
                        Make default
                      </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => setEditing(b)}>
                      Edit
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {list.filter((b) => b.is_active).length > 1 && <Channels brands={list.filter((b) => b.is_active)} onChange={refresh} />}
        </div>
      </div>
      {editing && <BrandDialog brand={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={refresh} />}
    </div>
  );
}

function BrandDialog({ brand, onClose, onSaved }: { brand: Brand | null; onClose: () => void; onSaved: () => void }) {
  const moneyOn = useMoneyOn();
  const entities = useEntities();
  const [v, setV] = useState({
    name: brand?.name ?? "",
    colour: brand?.colour ?? "",
    logo_url: brand?.logo_url ?? "",
    website: brand?.website ?? "",
    billing_entity_id: brand?.billing_entity_id ?? "",
    is_active: brand?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const body = {
      name: v.name,
      colour: v.colour || null,
      logo_url: v.logo_url || null,
      website: v.website || null,
      billing_entity_id: v.billing_entity_id || null,
      is_active: v.is_active,
    };
    try {
      if (brand) unwrap(await api.PUT("/api/v1/brands/{brand_id}", { params: { path: { brand_id: brand.id } }, body }));
      else unwrap(await api.POST("/api/v1/brands", { body }));
      onSaved();
      toast.success("Saved");
      onClose();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{brand ? `Edit ${brand.name}` : "New brand"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="space-y-1.5">
            <Label htmlFor="brand-name">Name</Label>
            <Input id="brand-name" value={v.name} maxLength={80} onChange={(e) => setV({ ...v, name: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="brand-colour">Colour</Label>
            <div className="flex items-center gap-2">
              <input
                type="color"
                aria-label="Pick a colour"
                value={v.colour || "#1d1d1f"}
                onChange={(e) => setV({ ...v, colour: e.target.value })}
                className="h-8 w-10 rounded border"
              />
              <Input id="brand-colour" value={v.colour} placeholder="#1d1d1f" onChange={(e) => setV({ ...v, colour: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="brand-logo">Logo address</Label>
            <Input id="brand-logo" value={v.logo_url} placeholder="https://…/logo.png" onChange={(e) => setV({ ...v, logo_url: e.target.value })} />
            <p className="text-xs text-muted-foreground">Shown on this brand&apos;s form pages. Use an https address.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="brand-website">Website</Label>
            <Input id="brand-website" value={v.website} placeholder="https://…" onChange={(e) => setV({ ...v, website: e.target.value })} />
          </div>
          {moneyOn && (
            <div className="space-y-1.5">
              <Label htmlFor="brand-entity">Invoices from</Label>
              <NativeSelect id="brand-entity" value={v.billing_entity_id} onChange={(e) => setV({ ...v, billing_entity_id: e.target.value })}>
                <option value="">The default billing entity</option>
                {(entities.data ?? [])
                  .filter((e) => e.is_active)
                  .map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
              </NativeSelect>
              <p className="text-xs text-muted-foreground">This brand&apos;s invoices use that entity&apos;s name, address, tax number and numbering.</p>
            </div>
          )}
          {brand && (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.target.checked })} />
              Active (switched-off brands keep their records but can&apos;t be chosen)
            </label>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving || !v.name.trim()} onClick={save}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Which inbox and which WhatsApp number belong to which brand. */
function Channels({ brands, onChange }: { brands: Brand[]; onChange: () => void }) {
  const qc = useQueryClient();
  const channels = useQuery({ queryKey: ["brand-channels"], queryFn: async () => unwrap(await api.GET("/api/v1/brands/channels")) });

  async function setBox(id: string, brand_id: string) {
    try {
      unwrap(await api.PUT("/api/v1/brands/channels/mailboxes/{mailbox_id}", { params: { path: { mailbox_id: id } }, body: { brand_id: brand_id || null } }));
      qc.invalidateQueries({ queryKey: ["brand-channels"] });
      onChange();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function setWa(brand_id: string) {
    try {
      unwrap(await api.PUT("/api/v1/brands/channels/whatsapp", { body: { brand_id: brand_id || null } }));
      qc.invalidateQueries({ queryKey: ["brand-channels"] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const data = channels.data;
  if (!data || (data.mailboxes.length === 0 && !data.whatsapp)) return null;
  const picker = (value: string | null | undefined, onPick: (id: string) => void, label: string) => (
    <NativeSelect aria-label={label} className="w-44" value={value ?? ""} onChange={(e) => onPick(e.target.value)}>
      <option value="">No brand (default)</option>
      {brands.map((b) => (
        <option key={b.id} value={b.id}>
          {b.name}
        </option>
      ))}
    </NativeSelect>
  );
  return (
    <div className="surface space-y-3 p-4 text-sm">
      <div>
        <h2 className="font-semibold">Inboxes and WhatsApp number</h2>
        <p className="text-muted-foreground">Leads that come in through one of these get its brand.</p>
      </div>
      <ul className="divide-y">
        {data.mailboxes.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-2 py-2">
            <span className="min-w-0 flex-1 truncate">{m.email_address}</span>
            {picker(m.brand_id, (id) => setBox(m.id, id), `Brand of ${m.email_address}`)}
          </li>
        ))}
        {data.whatsapp && (
          <li className="flex flex-wrap items-center gap-2 py-2">
            <span className="min-w-0 flex-1 truncate">WhatsApp {data.whatsapp.display_number ?? ""}</span>
            {picker(data.whatsapp.brand_id, setWa, "Brand of the WhatsApp number")}
          </li>
        )}
      </ul>
    </div>
  );
}
