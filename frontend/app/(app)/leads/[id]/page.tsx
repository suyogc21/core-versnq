"use client";

import { useParams } from "next/navigation";

import { LeadRecord } from "@/components/crm/lead-record";

export default function LeadPage() {
  const { id } = useParams<{ id: string }>();
  return <LeadRecord key={id} leadId={id} />;
}
