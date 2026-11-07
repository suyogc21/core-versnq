import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Label + input + error line, wired for react-hook-form's register(). */
export function Field({
  id,
  label,
  error,
  hint,
  ...input
}: React.ComponentProps<typeof Input> & { id: string; label: string; error?: string; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} aria-invalid={Boolean(error)} {...input} />
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

export const PASSWORD_RULE = { minLength: 10, maxLength: 200 } as const;
