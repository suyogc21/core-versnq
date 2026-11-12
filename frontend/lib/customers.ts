"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components, paths } from "@/lib/api/schema";

export type Customer = components["schemas"]["CustomerOut"];
export type Checklist = components["schemas"]["ChecklistOut"];
export type CustomerDocument = components["schemas"]["DocumentOut"];
export type StoredFile = components["schemas"]["FileOut"];
export type Requirement = components["schemas"]["RequirementOut"];
export type CustomerLink = components["schemas"]["CustomerLinkOut"];
export type CustomerSettings = components["schemas"]["CustomerSettings"];
export type PublicLink = components["schemas"]["PublicLinkOut"];
export type CustomerQuery = NonNullable<paths["/api/v1/customers"]["get"]["parameters"]["query"]>;

export function useCustomers(query: CustomerQuery, enabled = true) {
  return useQuery({ queryKey: ["customers", query], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/customers", { params: { query } })) });
}
export function useCustomer(id: string) {
  return useQuery({
    queryKey: ["customer", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/customers/{customer_id}", { params: { path: { customer_id: id } } })),
  });
}
/** The lead's customer record, or null while it is still a lead. */
export function useLeadCustomer(leadId: string, enabled = true) {
  return useQuery({
    queryKey: ["customer", "of-lead", leadId],
    enabled,
    queryFn: async () => unwrap(await api.GET("/api/v1/leads/{lead_id}/customer", { params: { path: { lead_id: leadId } } })),
  });
}
export function useChecklist(customerId: string) {
  return useQuery({
    queryKey: ["checklist", customerId],
    queryFn: async () => unwrap(await api.GET("/api/v1/customers/{customer_id}/documents", { params: { path: { customer_id: customerId } } })),
  });
}
export function useCustomerLinks(customerId: string) {
  return useQuery({
    queryKey: ["customer-links", customerId],
    queryFn: async () => unwrap(await api.GET("/api/v1/customers/{customer_id}/links", { params: { path: { customer_id: customerId } } })),
  });
}
export function useRequirements() {
  return useQuery({ queryKey: ["requirements"], queryFn: async () => unwrap(await api.GET("/api/v1/document-requirements")) });
}
export function useCustomerFields() {
  return useQuery({ queryKey: ["fields", "customer"], queryFn: async () => unwrap(await api.GET("/api/v1/custom-fields", { params: { query: { entity: "customer" } } })) });
}
export function useCustomerSettings() {
  return useQuery({ queryKey: ["customer-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/customer-settings")) });
}
export function useStorage(enabled = true) {
  return useQuery({ queryKey: ["storage"], enabled, queryFn: async () => unwrap(await api.GET("/api/v1/storage")) });
}

/** After any customer change: refresh everything that shows customers. */
export function useRefreshCustomers() {
  const qc = useQueryClient();
  return () => {
    for (const key of ["customers", "customer", "checklist", "customer-links", "storage", "timeline", "lead", "leads", "tasks"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
}

const SHRINK_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const SHRINK_ABOVE = 600 * 1024;
const MAX_SIDE = 2000;

/** Phone photos are 3–4 MB; we send them at most 2000 px wide as a good-quality JPEG
 * (usually 300–500 KB), so the company's storage lasts far longer (Decision log #32).
 * PDFs and anything the browser cannot draw are sent untouched. */
export async function shrinkPhoto(file: File): Promise<File> {
  if (!SHRINK_TYPES.has(file.type) || file.size <= SHRINK_ABOVE) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.fillStyle = "#fff"; // transparent PNGs get a white page, not black
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, "image/jpeg", 0.85));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;
  }
}

export const MAX_FILE_BYTES = 10 * 1024 * 1024;

export async function uploadFile(customerId: string, documentId: string, file: File) {
  const ready = await shrinkPhoto(file);
  if (ready.size > MAX_FILE_BYTES) throw new Error(`${file.name} is larger than 10 MB`);
  return unwrap(
    await api.POST("/api/v1/customers/{customer_id}/documents/{document_id}/files", {
      params: { path: { customer_id: customerId, document_id: documentId }, query: { name: ready.name } },
      body: ready as unknown as string,
      bodySerializer: (b: unknown) => b as BodyInit,
      headers: { "Content-Type": "application/octet-stream" },
    }),
  );
}

/** Fetch a file with the signed-in person's access and hand back a temporary browser URL. */
export async function fileUrl(customerId: string, fileId: string, download = false): Promise<string> {
  const { data, error, response } = await api.GET("/api/v1/customers/{customer_id}/files/{file_id}", {
    params: { path: { customer_id: customerId, file_id: fileId }, query: { download } },
    parseAs: "blob",
  });
  if (error || !data) throw new Error(response.status === 404 ? "This file could not be found" : "Could not open the file");
  return URL.createObjectURL(data as Blob);
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export const DOC_STATUS: Record<string, { label: string; tone: string }> = {
  pending: { label: "Pending", tone: "bg-muted text-muted-foreground" },
  received: { label: "Received", tone: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  verified: { label: "Verified", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  rejected: { label: "Rejected", tone: "bg-red-500/10 text-red-700 dark:text-red-300" },
};

/** The customer's page lives on the company's own address. */
export function linkAddress(code: string): string {
  return `${window.location.origin}/c/${code}`;
}

// ---------- public (no login): the customer's link page ----------
async function publicCall<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1/public/links/${path}`, init);
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Something went wrong. Please try again.");
  return body as T;
}

export const publicLink = {
  get: (code: string) => publicCall<PublicLink>(encodeURIComponent(code)),
  async upload(code: string, documentId: string, file: File) {
    const ready = await shrinkPhoto(file);
    if (ready.size > MAX_FILE_BYTES) throw new Error(`${file.name} is larger than 10 MB`);
    return publicCall<PublicLink>(`${encodeURIComponent(code)}/documents/${documentId}/files?name=${encodeURIComponent(ready.name)}`, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: ready,
    });
  },
  submit: (code: string, values: Record<string, unknown>) =>
    publicCall<void>(`${encodeURIComponent(code)}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ values }),
    }),
};
