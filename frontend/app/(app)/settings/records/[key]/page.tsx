"use client";

import { useParams } from "next/navigation";

import { RecordTypeSettings } from "@/components/crm/record-settings";

export default function RecordTypeSettingsPage() {
  const { key } = useParams<{ key: string }>();
  return <RecordTypeSettings key={key} typeKey={key} />;
}
