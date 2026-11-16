"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { PageHeader } from "@/components/app/app-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { useBrandChoices } from "@/lib/brands";

type Saved = components["schemas"]["PageOut"];
type Block = { type: string; text?: string; level?: number; url?: string; alt?: string; form_id?: string; label?: string; _k: number };

const KINDS: { type: string; label: string; make: () => Omit<Block, "_k"> }[] = [
  { type: "heading", label: "Heading", make: () => ({ type: "heading", text: "", level: 2 }) },
  { type: "text", label: "Text", make: () => ({ type: "text", text: "" }) },
  { type: "image", label: "Image", make: () => ({ type: "image", url: "", alt: "" }) },
  { type: "video", label: "Video", make: () => ({ type: "video", url: "" }) },
  { type: "form", label: "Form", make: () => ({ type: "form", form_id: "" }) },
  { type: "button", label: "Button", make: () => ({ type: "button", label: "", url: "" }) },
];
let counter = 0;

/** Marketing → a landing page's builder (batch 5a). */
export default function LandingPageEditor() {
  const { id } = useParams<{ id: string }>();
  const page = useQuery({ queryKey: ["landing-page", id], queryFn: async () => unwrap(await api.GET("/api/v1/landing-pages/{page_id}", { params: { path: { page_id: id } } })) });
  if (!page.data) return <p className="p-6 text-sm text-muted-foreground">{page.isError ? "Page not found" : "Loading…"}</p>;
  return <Editor key={page.data.updated_at} saved={page.data} />;
}

function Editor({ saved }: { saved: Saved }) {
  const qc = useQueryClient();
  const router = useRouter();
  const brands = useBrandChoices();
  const forms = useQuery({
    queryKey: ["capture-sources"],
    queryFn: async () => unwrap(await api.GET("/api/v1/capture-sources")),
    retry: false,
  });
  const hosted = (forms.data ?? []).filter((f) => f.hosted && f.public_id);
  const [title, setTitle] = useState(saved.title);
  const [slug, setSlug] = useState(saved.slug);
  const [published, setPublished] = useState(saved.published);
  const [brandId, setBrandId] = useState(saved.brand_id ?? "");
  const [seoTitle, setSeoTitle] = useState(saved.seo_title ?? "");
  const [seoDescription, setSeoDescription] = useState(saved.seo_description ?? "");
  const [blocks, setBlocks] = useState<Block[]>(() => saved.blocks.map((b) => ({ ...(b as Omit<Block, "_k">), _k: ++counter })));
  const set = (i: number, patch: Partial<Block>) => setBlocks(blocks.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const move = (i: number, by: number) => {
    const out = [...blocks];
    [out[i], out[i + by]] = [out[i + by], out[i]];
    setBlocks(out);
  };

  async function save() {
    try {
      unwrap(
        await api.PUT("/api/v1/landing-pages/{page_id}", {
          params: { path: { page_id: saved.id } },
          body: {
            title,
            slug,
            published,
            brand_id: brandId || null,
            seo_title: seoTitle || null,
            seo_description: seoDescription || null,
            blocks: blocks.map(({ _k, ...b }) => {
              void _k;
              return b;
            }),
          },
        }),
      );
      qc.invalidateQueries({ queryKey: ["landing-page", saved.id] });
      qc.invalidateQueries({ queryKey: ["landing-pages"] });
      toast.success("Saved");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function remove() {
    if (!window.confirm("Delete this page? Its address stops working.")) return;
    try {
      unwrap(await api.DELETE("/api/v1/landing-pages/{page_id}", { params: { path: { page_id: saved.id } } }));
      qc.invalidateQueries({ queryKey: ["landing-pages"] });
      router.push("/landing-pages");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader back={{ href: "/landing-pages", label: "Landing pages" }} title={saved.title} />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-3xl space-y-5 p-4 text-sm sm:p-6">
          <section className="surface space-y-3 p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1">
                <Label htmlFor="title">Title</Label>
                <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="slug">Address</Label>
                <div className="flex items-center gap-1">
                  <span className="text-muted-foreground">/p/</span>
                  <Input id="slug" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} />
                </div>
              </div>
              <div className="space-y-1">
                <Label htmlFor="seo-title">Title in search results</Label>
                <Input id="seo-title" value={seoTitle} onChange={(e) => setSeoTitle(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label htmlFor="seo-desc">Description in search results</Label>
                <Input id="seo-desc" value={seoDescription} onChange={(e) => setSeoDescription(e.target.value)} />
              </div>
              {brands.length > 0 && (
                <div className="space-y-1">
                  <Label htmlFor="brand">Brand</Label>
                  <NativeSelect id="brand" value={brandId} onChange={(e) => setBrandId(e.target.value)}>
                    <option value="">Company</option>
                    {brands.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              )}
            </div>
            <label className="flex items-center gap-2">
              <Switch aria-label="Published" checked={published} onCheckedChange={setPublished} />
              {published ? "Published: anyone with the address can see it" : "Draft: only you can see it here"}
            </label>
            <p className="text-muted-foreground">
              {saved.visits} visits · {saved.leads} leads
              {saved.published && (
                <>
                  {" · "}
                  <a href={saved.path} target="_blank" rel="noopener" className="underline">
                    Open page
                  </a>
                </>
              )}
            </p>
          </section>

          <ol className="space-y-2">
            {blocks.map((b, i) => (
              <li key={b._k} className="surface space-y-2 p-3" data-block={i + 1}>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium tracking-wide uppercase">{KINDS.find((k) => k.type === b.type)?.label ?? b.type}</span>
                  <div className="ml-auto flex">
                    <Button size="icon-sm" variant="ghost" aria-label={`Move block ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                      <ArrowUp />
                    </Button>
                    <Button size="icon-sm" variant="ghost" aria-label={`Move block ${i + 1} down`} disabled={i === blocks.length - 1} onClick={() => move(i, 1)}>
                      <ArrowDown />
                    </Button>
                    <Button size="icon-sm" variant="ghost" aria-label={`Remove block ${i + 1}`} onClick={() => setBlocks(blocks.filter((_, j) => j !== i))}>
                      <Trash2 />
                    </Button>
                  </div>
                </div>
                {b.type === "heading" && (
                  <div className="flex gap-2">
                    <Input aria-label={`Block ${i + 1} heading`} value={b.text ?? ""} onChange={(e) => set(i, { text: e.target.value })} />
                    <NativeSelect aria-label={`Block ${i + 1} size`} className="w-28" value={b.level ?? 1} onChange={(e) => set(i, { level: Number(e.target.value) })}>
                      <option value={1}>Large</option>
                      <option value={2}>Medium</option>
                    </NativeSelect>
                  </div>
                )}
                {b.type === "text" && <Textarea aria-label={`Block ${i + 1} text`} rows={4} value={b.text ?? ""} onChange={(e) => set(i, { text: e.target.value })} />}
                {b.type === "image" && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Input aria-label={`Block ${i + 1} image address`} placeholder="https://…/photo.jpg" value={b.url ?? ""} onChange={(e) => set(i, { url: e.target.value })} />
                    <Input aria-label={`Block ${i + 1} image description`} placeholder="What it shows (for screen readers)" value={b.alt ?? ""} onChange={(e) => set(i, { alt: e.target.value })} />
                  </div>
                )}
                {b.type === "video" && <Input aria-label={`Block ${i + 1} video`} placeholder="A YouTube or Vimeo address" value={b.url ?? ""} onChange={(e) => set(i, { url: e.target.value })} />}
                {b.type === "form" &&
                  (forms.isError ? (
                    <p className="text-muted-foreground">Choosing forms needs the &quot;set up&quot; permission (Settings → Lead capture).</p>
                  ) : (
                    <NativeSelect aria-label={`Block ${i + 1} form`} value={b.form_id ?? ""} onChange={(e) => set(i, { form_id: e.target.value })}>
                      <option value="">Choose a form…</option>
                      {hosted.map((f) => (
                        <option key={f.id} value={f.public_id ?? ""}>
                          {f.name}
                        </option>
                      ))}
                    </NativeSelect>
                  ))}
                {b.type === "button" && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Input aria-label={`Block ${i + 1} button label`} placeholder="Label" value={b.label ?? ""} onChange={(e) => set(i, { label: e.target.value })} />
                    <Input aria-label={`Block ${i + 1} button link`} placeholder="https://…" value={b.url ?? ""} onChange={(e) => set(i, { url: e.target.value })} />
                  </div>
                )}
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-2">
            {KINDS.map((k) => (
              <Button key={k.type} size="sm" variant="outline" onClick={() => setBlocks([...blocks, { ...k.make(), _k: ++counter }])}>
                + {k.label}
              </Button>
            ))}
          </div>
          <div className="flex gap-2">
            <Button onClick={save}>Save</Button>
            <Button variant="ghost" onClick={remove}>
              Delete page
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
