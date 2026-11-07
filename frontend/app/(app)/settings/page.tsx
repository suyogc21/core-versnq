"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/app/app-shell";
import { Field } from "@/components/app/field";
import { NativeSelect } from "@/components/app/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { type WorkspaceSettings, useWorkspaceSettings } from "@/lib/settings";
import { DEFAULT_ACCENT } from "@/lib/theme";

// The record types whose names a workspace can change (matches the backend's LABEL_KEYS).
const LABEL_KEYS = [
  ["lead", "Lead"],
  ["contact", "Contact"],
  ["deal", "Deal"],
  ["customer", "Customer"],
  ["pipeline", "Pipeline"],
] as const;

type Label = { singular: string; plural: string };
type Form = {
  labels: Record<string, Label>;
  timezone: string;
  locale: string;
  default_country: string;
  primary_color: string;
  logo_url: string;
};

// Browsers list some zones under old names (e.g. Asia/Calcutta); always offer the saved one.
const timezones = (current: string) => [...new Set([current, ...Intl.supportedValuesOf("timeZone")])].sort();

export default function SettingsPage() {
  const settings = useWorkspaceSettings();
  return (
    <>
      <PageHeader title="Settings" />
      {settings.data ? (
        <SettingsForm settings={settings.data} />
      ) : (
        <p className="p-4 text-muted-foreground">Loading…</p>
      )}
    </>
  );
}

function SettingsForm({ settings }: { settings: WorkspaceSettings }) {
  const queryClient = useQueryClient();
  const branding = settings.branding as { primary_color?: string; logo_url?: string };
  const form = useForm<Form>({
    defaultValues: {
      labels: settings.labels as Record<string, Label>,
      timezone: settings.timezone,
      locale: settings.locale,
      default_country: settings.default_country,
      primary_color: branding.primary_color ?? DEFAULT_ACCENT,
      logo_url: branding.logo_url ?? "",
    },
  });
  const { errors, isSubmitting, isDirty } = form.formState;

  const submit = form.handleSubmit(async (v) => {
    try {
      const data = unwrap(
        await api.PATCH("/api/v1/settings", {
          body: {
            labels: v.labels,
            timezone: v.timezone,
            locale: v.locale,
            default_country: v.default_country.toUpperCase(),
            branding: { primary_color: v.primary_color, logo_url: v.logo_url || null },
          },
        }),
      );
      queryClient.setQueryData(["settings"], data);
      form.reset(form.getValues());
      toast.success("Settings saved.");
    } catch (e) {
      form.setError("root", { message: (e as Error).message });
    }
  });

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-2xl space-y-8 p-8">
      <section className="space-y-3">
        <div>
          <h2 className="font-semibold">Names for your records</h2>
          <p className="text-muted-foreground">
            Use your business&apos;s own words. An academy might call a lead a &quot;Student&quot;.
          </p>
        </div>
        <div className="grid grid-cols-[8rem_1fr_1fr] items-center gap-x-3 gap-y-2">
          <span />
          <span className="text-xs text-muted-foreground">Singular</span>
          <span className="text-xs text-muted-foreground">Plural</span>
          {LABEL_KEYS.map(([key, name]) => (
            <div key={key} className="contents">
              <span className="text-muted-foreground">{name}</span>
              <Input
                aria-label={`${name} singular`}
                {...form.register(`labels.${key}.singular`, { required: true, maxLength: 60 })}
              />
              <Input
                aria-label={`${name} plural`}
                {...form.register(`labels.${key}.plural`, { required: true, maxLength: 60 })}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Region</h2>
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="timezone">Time zone</Label>
            <NativeSelect id="timezone" {...form.register("timezone")}>
              {timezones(settings.timezone).map((tz) => (
                <option key={tz}>{tz}</option>
              ))}
            </NativeSelect>
          </div>
          <Field
            id="default_country"
            label="Default country"
            hint="Two letters, e.g. IN, AE, US"
            maxLength={2}
            error={errors.default_country?.message}
            {...form.register("default_country", {
              pattern: { value: /^[A-Za-z]{2}$/, message: "Use a two-letter code" },
            })}
          />
          <Field
            id="locale"
            label="Language"
            hint="e.g. en or en-IN"
            error={errors.locale?.message}
            {...form.register("locale", {
              pattern: { value: /^[a-z]{2}(-[A-Z]{2})?$/, message: "Use a code like en or en-IN" },
            })}
          />
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Branding</h2>
        <div className="grid grid-cols-[auto_1fr] items-end gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="primary_color">Colour</Label>
            <input
              id="primary_color"
              type="color"
              defaultValue={branding.primary_color ?? DEFAULT_ACCENT}
              className="h-8 w-14 cursor-pointer rounded-lg border bg-transparent"
              {...form.register("primary_color")}
            />
          </div>
          <Field
            id="logo_url"
            label="Logo URL"
            placeholder="https://…"
            error={errors.logo_url?.message}
            {...form.register("logo_url", {
              pattern: { value: /^https:\/\/\S+$/, message: "Use an https:// link" },
            })}
          />
        </div>
      </section>

      {errors.root && <p className="text-destructive">{errors.root.message}</p>}
      <div className="flex justify-end gap-2 border-t pt-4">
        <Button type="button" variant="outline" disabled={!isDirty} onClick={() => form.reset()}>
          Discard
        </Button>
        <Button type="submit" disabled={!isDirty || isSubmitting}>
          Save settings
        </Button>
      </div>
    </form>
  );
}
