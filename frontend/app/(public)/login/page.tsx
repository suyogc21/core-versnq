"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { AuthCard } from "@/components/app/auth-card";
import { Field } from "@/components/app/field";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

type Creds = { email: string; password: string };

export default function LoginPage() {
  const { status, login, verifyTwoFactor } = useAuth();
  const router = useRouter();
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const creds = useForm<Creds>();
  const code = useForm<{ code: string }>();

  useEffect(() => {
    if (status === "signed-in") router.replace("/");
  }, [status, router]);

  const submitCreds = creds.handleSubmit(async ({ email, password }) => {
    setError(null);
    try {
      const result = await login(email, password);
      if (!result.done) setChallenge(result.challengeToken);
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

  if (challenge) {
    return (
      <AuthCard title="Two-factor code" description="Enter the 6-digit code from your authenticator app.">
        <form onSubmit={submitCode} className="space-y-4">
          <Field
            id="code"
            label="Code"
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            maxLength={6}
            error={error ?? undefined}
            {...code.register("code", { required: true, pattern: /^\d{6}$/ })}
          />
          <Button type="submit" className="w-full" disabled={code.formState.isSubmitting}>
            Verify
          </Button>
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
