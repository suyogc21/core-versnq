"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Field } from "@/components/app/field";
import { NativeSelect } from "@/components/app/native-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

const PAGE = 50;

export default function CompaniesPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<"" | "active" | "suspended">("");
  const [page, setPage] = useState(0);
  const [creating, setCreating] = useState(false);
  const companies = useQuery({
    queryKey: ["tenants", q, status, page],
    queryFn: async () =>
      unwrap(
        await api.GET("/platform/tenants", {
          params: { query: { q: q || undefined, status: status || undefined, limit: PAGE, offset: page * PAGE } },
        }),
      ),
  });

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-base font-semibold">Companies</h1>
        <Input
          placeholder="Search name or address"
          className="h-8 w-56"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(0);
          }}
        />
        <NativeSelect
          aria-label="Status"
          className="w-36"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as typeof status);
            setPage(0);
          }}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
        </NativeSelect>
        <Button onClick={() => setCreating(true)}>Create company</Button>
      </div>
      {companies.isLoading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : companies.isError ? (
        <p className="text-destructive">{companies.error.message}</p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Address</TableHead>
                <TableHead>Industry pack</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {companies.data?.map((t) => (
                <TableRow key={t.id}>
                  <TableCell>
                    <Link href={`/companies/${t.id}`} className="font-medium hover:underline">
                      {t.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{t.slug}</TableCell>
                  <TableCell>{t.industry_pack}</TableCell>
                  <TableCell>
                    <Badge variant={t.status === "active" ? "secondary" : "destructive"} className="capitalize">
                      {t.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{new Date(t.created_at).toLocaleDateString()}</TableCell>
                </TableRow>
              ))}
              {companies.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    No companies match.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={(companies.data?.length ?? 0) < PAGE}
              onClick={() => setPage(page + 1)}
            >
              Next
            </Button>
          </div>
        </>
      )}
      {creating && <CreateCompanyDialog onClose={() => setCreating(false)} />}
    </>
  );
}

type CreateForm = {
  name: string;
  slug: string;
  industry_pack: string;
  timezone: string;
  default_country: string;
  owner_name: string;
  owner_email: string;
};

function CreateCompanyDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const packs = useQuery({ queryKey: ["packs"], queryFn: async () => unwrap(await api.GET("/platform/packs")) });
  const form = useForm<CreateForm>({
    defaultValues: { industry_pack: "generic", timezone: "Asia/Kolkata", default_country: "IN" },
  });
  const { errors, isSubmitting } = form.formState;

  const submit = form.handleSubmit(async (body) => {
    try {
      const created = unwrap(
        await api.POST("/platform/tenants", {
          body: { ...body, slug: body.slug.toLowerCase(), default_country: body.default_country.toUpperCase() },
        }),
      );
      queryClient.invalidateQueries({ queryKey: ["tenants"] });
      if (created.invite_sent) toast.success(`${created.name} created. The Owner has been invited.`);
      else toast.error(`${created.name} created, but the Owner invite could not be sent. Resend it from the company page.`);
      router.push(`/companies/${created.id}`);
    } catch (e) {
      form.setError("root", { message: (e as Error).message });
    }
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create company</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <Field id="name" label="Company name" autoFocus error={errors.name?.message} {...form.register("name", { required: "Enter a name" })} />
          <Field
            id="slug"
            label="Address"
            hint="Lowercase letters, numbers and hyphens. They sign in at <address>.core.versnq.in"
            error={errors.slug?.message}
            {...form.register("slug", {
              required: "Enter an address",
              pattern: { value: /^[a-zA-Z0-9-]+$/, message: "Letters, numbers and hyphens only" },
            })}
          />
          <div className="space-y-1.5">
            <Label htmlFor="industry_pack">Industry pack</Label>
            <NativeSelect id="industry_pack" {...form.register("industry_pack")}>
              {(packs.data ?? [{ key: "generic", name: "Generic" }]).map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field id="timezone" label="Time zone" {...form.register("timezone", { required: true })} />
            <Field
              id="default_country"
              label="Country"
              maxLength={2}
              error={errors.default_country?.message}
              {...form.register("default_country", {
                pattern: { value: /^[A-Za-z]{2}$/, message: "Two-letter code" },
              })}
            />
          </div>
          <Field id="owner_name" label="Owner name" error={errors.owner_name?.message} {...form.register("owner_name", { required: "Enter the Owner's name" })} />
          <Field
            id="owner_email"
            label="Owner email"
            type="email"
            error={errors.owner_email?.message}
            {...form.register("owner_email", { required: "Enter the Owner's email" })}
          />
          {errors.root && <p className="text-xs text-destructive">{errors.root.message}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              Create and invite Owner
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
