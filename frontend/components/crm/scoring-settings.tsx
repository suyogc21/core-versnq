"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { NativeSelect } from "@/components/app/native-select";
import { ConditionRow, describeCondition, useFieldChoices } from "@/components/crm/rule-builder";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { useActivityTypes } from "@/lib/crm";
import { type Condition, type ScoreRule, useScoreRules, useScoreSettings } from "@/lib/organise";
import { useLabels } from "@/lib/settings";
import { cn } from "@/lib/utils";

function useSave() {
  const qc = useQueryClient();
  return async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      for (const k of ["score-rules", "score-settings"]) qc.invalidateQueries({ queryKey: [k] });
      if (ok) toast.success(ok);
      return true;
    } catch (e) {
      toast.error((e as Error).message);
      return false;
    }
  };
}

export function ScoringSettings() {
  const label = useLabels();
  const rules = useScoreRules();
  const list = rules.data ?? [];
  return (
    <div className="space-y-8">
      <p className="text-sm text-muted-foreground">
        Every {label("lead").toLowerCase()} gets a score: <b>fit</b> points for who they are, plus <b>engagement</b> points for what happened recently. The
        score puts them in Hot, Warm or Cold. Changes re-score everyone within a minute.
      </p>
      <Thresholds />
      <FitRules rules={list.filter((r) => r.kind === "fit")} />
      <EngagementRules rules={list.filter((r) => r.kind === "engagement")} />
    </div>
  );
}

function Thresholds() {
  const settings = useScoreSettings();
  const save = useSave();
  const s = settings.data;
  const [v, setV] = useState<{ engagement_days: string; hot_score: string; warm_score: string } | null>(null);
  if (!s) return null;
  const cur = v ?? { engagement_days: String(s.engagement_days), hot_score: String(s.hot_score), warm_score: String(s.warm_score) };
  return (
    <section className="space-y-3">
      <h3 className="font-medium">Bands</h3>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await save(
            async () =>
              unwrap(
                await api.PUT("/api/v1/score-settings", {
                  body: { engagement_days: Number(cur.engagement_days), hot_score: Number(cur.hot_score), warm_score: Number(cur.warm_score) },
                }),
              ),
            "Saved",
          );
          if (ok) setV(null);
        }}
      >
        <div className="space-y-1">
          <Label htmlFor="s-hot">Hot from</Label>
          <Input id="s-hot" type="number" className="h-8 w-24" value={cur.hot_score} onChange={(e) => setV({ ...cur, hot_score: e.target.value })} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="s-warm">Warm from</Label>
          <Input id="s-warm" type="number" className="h-8 w-24" value={cur.warm_score} onChange={(e) => setV({ ...cur, warm_score: e.target.value })} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="s-days">Count activity from the last</Label>
          <div className="flex items-center gap-1.5">
            <Input id="s-days" type="number" className="h-8 w-20" value={cur.engagement_days} onChange={(e) => setV({ ...cur, engagement_days: e.target.value })} />
            <span className="text-sm text-muted-foreground">days</span>
          </div>
        </div>
        <Button size="sm" type="submit" disabled={!v}>
          Save
        </Button>
      </form>
    </section>
  );
}

function Points({ value, onSave }: { value: number; onSave: (n: number) => void }) {
  const [v, setV] = useState(String(value));
  return (
    <Input
      aria-label="Points"
      type="number"
      className={cn("h-7 w-20 text-end tabular-nums", value < 0 && "text-destructive")}
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => Number(v) !== value && v !== "" && onSave(Number(v))}
    />
  );
}

function RuleShell({ rule, children }: { rule: ScoreRule; children: React.ReactNode }) {
  const save = useSave();
  const patch = (body: Record<string, unknown>) =>
    save(async () => unwrap(await api.PATCH("/api/v1/score-rules/{rule_id}", { params: { path: { rule_id: rule.id } }, body })));
  return (
    <div className="flex items-center gap-3 px-3 py-2 text-sm">
      <Switch aria-label="Rule on" checked={rule.is_active} onCheckedChange={(on) => patch({ is_active: on })} />
      <span className={cn("min-w-0 flex-1 truncate", !rule.is_active && "text-muted-foreground line-through")}>{children}</span>
      <Points value={rule.points} onSave={(points) => patch({ points })} />
      <button
        aria-label="Delete rule"
        className="text-muted-foreground hover:text-destructive"
        onClick={() => save(async () => unwrap(await api.DELETE("/api/v1/score-rules/{rule_id}", { params: { path: { rule_id: rule.id } } })), "Deleted")}
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

function FitRules({ rules }: { rules: ScoreRule[] }) {
  const choices = useFieldChoices("lead", { forFit: true });
  const save = useSave();
  const [draft, setDraft] = useState<Condition | null>(null);
  const [points, setPoints] = useState("10");
  return (
    <section className="space-y-3">
      <h3 className="font-medium">Fit — who they are</h3>
      <div className="divide-y surface">
        {rules.length === 0 && <p className="px-3 py-3 text-sm text-muted-foreground">No fit rules yet.</p>}
        {rules.map((r) => (
          <RuleShell key={r.id} rule={r}>
            {describeCondition(r.condition as Condition, choices)}
          </RuleShell>
        ))}
      </div>
      {draft ? (
        <div className="surface space-y-2 p-4">
          <ConditionRow choices={choices} value={draft} onChange={setDraft} onRemove={() => setDraft(null)} />
          <div className="flex items-center gap-2">
            <span className="text-sm">Points</span>
            <Input aria-label="New rule points" type="number" className="h-8 w-24" value={points} onChange={(e) => setPoints(e.target.value)} />
            <Button
              size="sm"
              disabled={!draft.field}
              onClick={async () => {
                const ok = await save(async () => unwrap(await api.POST("/api/v1/score-rules", { body: { kind: "fit", condition: draft, points: Number(points) } })), "Rule added");
                if (ok) setDraft(null);
              }}
            >
              Add rule
            </Button>
          </div>
        </div>
      ) : (
        <Button size="sm" variant="outline" onClick={() => setDraft({ field: "", op: "is" })}>
          <Plus /> Fit rule
        </Button>
      )}
    </section>
  );
}

function EngagementRules({ rules }: { rules: ScoreRule[] }) {
  const types = useActivityTypes();
  const save = useSave();
  const loggable = (types.data ?? []).filter((t) => t.is_loggable && t.is_active);
  const [type, setType] = useState("");
  const [outcome, setOutcome] = useState("");
  const [points, setPoints] = useState("10");
  const typeOf = (key: string | null) => (types.data ?? []).find((t) => t.key === key);
  const outcomes = (key: string) =>
    ((typeOf(key)?.fields ?? []) as { key: string; options?: { value: string; label: string }[] }[]).find((f) => f.key === "disposition")?.options ?? [];
  return (
    <section className="space-y-3">
      <h3 className="font-medium">Engagement — what they did recently</h3>
      <div className="divide-y surface">
        {rules.length === 0 && <p className="px-3 py-3 text-sm text-muted-foreground">No engagement rules yet.</p>}
        {rules.map((r) => (
          <RuleShell key={r.id} rule={r}>
            Each {typeOf(r.activity_type_key)?.label ?? r.activity_type_key}
            {r.disposition ? ` with outcome “${outcomes(r.activity_type_key ?? "").find((o) => o.value === r.disposition)?.label ?? r.disposition}”` : ""}
          </RuleShell>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect aria-label="Activity" className="h-8 w-auto" value={type} onChange={(e) => (setType(e.target.value), setOutcome(""))}>
          <option value="">Each activity of type…</option>
          {loggable.map((t) => (
            <option key={t.key} value={t.key}>
              {t.label}
            </option>
          ))}
        </NativeSelect>
        {type && outcomes(type).length > 0 && (
          <NativeSelect aria-label="Outcome" className="h-8 w-auto" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">Any outcome</option>
            {outcomes(type).map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </NativeSelect>
        )}
        <Input aria-label="Engagement points" type="number" className="h-8 w-20" value={points} onChange={(e) => setPoints(e.target.value)} />
        <Button
          size="sm"
          variant="outline"
          disabled={!type}
          onClick={async () => {
            const ok = await save(
              async () =>
                unwrap(await api.POST("/api/v1/score-rules", { body: { kind: "engagement", activity_type_key: type, disposition: outcome || null, points: Number(points) } })),
              "Rule added",
            );
            if (ok) {
              setType("");
              setOutcome("");
            }
          }}
        >
          <Plus /> Engagement rule
        </Button>
      </div>
    </section>
  );
}
