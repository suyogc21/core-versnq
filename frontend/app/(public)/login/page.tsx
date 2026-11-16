"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard } from "@/components/app/auth-card";
import { Field } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { type CodeMethod, useAuth } from "@/lib/auth";

type Creds = { email: string; password: string };

/** Where to go after signing in: ?next= when it is a page of this app, otherwise My Day. */
function safeNext(): string {
  const next = new URLSearchParams(window.location.search).get("next") ?? "";
  return /^\/(?![/\\])/.test(next) ? next : "/";
}

export default function LoginPage() {
  const { status, login, verifyTwoFactor, resendCode } = useAuth();
  const router = useRouter();
  const [challenge, setChallenge] = useState<string | null>(null);
  const [method, setMethod] = useState<CodeMethod>("app");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const creds = useForm<Creds>();
  const code = useForm<{ code: string }>();

  useEffect(() => {
    if (status === "signed-in") router.replace(safeNext());
  }, [status, router]);

  const submitCreds = creds.handleSubmit(async ({ email, password }) => {
    setError(null);
    try {
      const result = await login(email, password);
      if (!result.done) {
        setMethod(result.method);
        setNotice(null);
        setChallenge(result.challengeToken);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  });

  const submitCode = code.handleSubmit(async ({ code: value }) => {
    setError(null);
    try {
      await verifyTwoFactor(challenge as string, value.trim());
    } catch (e) {
      setError((e as Error).message);
    }
  });

  const resend = async () => {
    setError(null);
    try {
      await resendCode(challenge as string);
      setNotice("A new code is on its way. The earlier one no longer works.");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (challenge) {
    const byEmail = method === "email";
    return (
      <AuthCard
        title={byEmail ? "Check your email" : "Two-factor code"}
        description={
          byEmail
            ? `We emailed a 6-digit code to ${creds.getValues("email")}. It works for 10 minutes. This browser will be remembered for 30 days.`
            : "Enter the 6-digit code from your authenticator app. Lost your phone? Enter one of your backup codes."
        }
      >
        <form onSubmit={submitCode} className="space-y-4">
          <Field
            id="code"
            label="Code"
            inputMode={byEmail ? "numeric" : "text"}
            autoComplete="one-time-code"
            autoFocus
            maxLength={byEmail ? 6 : 9}
            error={error ?? undefined}
            {...code.register("code", { required: true, pattern: byEmail ? /^\d{6}$/ : /^(\d{6}|[a-z0-9]{4}-?[a-z0-9]{4})$/i })}
          />
          {notice ? <p className="text-xs text-muted-foreground">{notice}</p> : null}
          <Button type="submit" className="w-full" disabled={code.formState.isSubmitting}>
            Verify
          </Button>
          {byEmail ? (
            <button type="button" className="w-full text-xs text-muted-foreground hover:underline" onClick={resend}>
              Didn&apos;t get it? Send a new code
            </button>
          ) : null}
          <button type="button" className="w-full text-xs text-muted-foreground" onClick={() => setChallenge(null)}>
            Use a different account
          </button>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Sign in">
      <form onSubmit={submitCreds} className="space-y-4">
        <Field id="email" label="Email" type="email" autoComplete="email" autoFocus {...creds.register("email", { required: true })} />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          {...creds.register("password", { required: true })}
        />
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        <Button type="submit" className="w-full" disabled={creds.formState.isSubmitting}>
          Sign in
        </Button>
        <Link href="/forgot-password" className="block text-center text-xs text-muted-foreground hover:underline">
          Forgot password?
        </Link>
      </form>
    </AuthCard>
  );
}
