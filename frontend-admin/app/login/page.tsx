"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { LoginForm } from "@/components/app/sign-in";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { status } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (status === "signed-in") router.replace("/");
  }, [status, router]);
  return <LoginForm />;
}
