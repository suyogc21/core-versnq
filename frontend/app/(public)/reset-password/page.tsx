"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { toast } from "sonner";

import { AuthCard } from "@/components/app/auth-card";
import { SetPasswordForm } from "@/components/app/set-password-form";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";

function Inner() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  if (!token) {
    return <AuthCard title="Choose a new password" description="This link is missing its token. Open the link from your email again." >{null}</AuthCard>;
  }
  return (
    <AuthCard title="Choose a new password">
      <SetPasswordForm
        submitLabel="Save new password"
        onSubmit={async (password) => {
          unwrap(await api.POST("/api/v1/auth/password/reset", { body: { token, password } }));
          toast.success("Password changed. Sign in with your new password.");
          router.replace("/login");
        }}
      />
    </AuthCard>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
