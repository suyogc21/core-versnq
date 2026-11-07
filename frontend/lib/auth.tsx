"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api, refreshAccessToken, tokenStore } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeOut"];
type Status = "loading" | "signed-out" | "signed-in";
type LoginResult = { done: true } | { done: false; challengeToken: string };

type AuthState = {
  status: Status;
  me: Me | null;
  can: (permission: string) => boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  verifyTwoFactor: (challengeToken: string, code: string) => Promise<void>;
  reloadMe: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const reloadMe = useCallback(async () => {
    const data = unwrap(await api.GET("/api/v1/auth/me"));
    setMe(data);
    setStatus("signed-in");
  }, []);

  useEffect(() => {
    // A page load has no access token: try the refresh cookie once.
    refreshAccessToken().then((ok) => (ok ? reloadMe() : setStatus("signed-out")));
  }, [reloadMe]);

  const login = useCallback(
    async (email: string, password: string): Promise<LoginResult> => {
      const data = unwrap(await api.POST("/api/v1/auth/login", { body: { email, password } }));
      if (data.two_factor_required && data.challenge_token) {
        return { done: false, challengeToken: data.challenge_token };
      }
      tokenStore.set(data.access_token ?? null);
      await reloadMe();
      return { done: true };
    },
    [reloadMe],
  );

  const verifyTwoFactor = useCallback(
    async (challengeToken: string, code: string) => {
      const data = unwrap(
        await api.POST("/api/v1/auth/2fa/verify", { body: { challenge_token: challengeToken, code } }),
      );
      tokenStore.set(data.access_token ?? null);
      await reloadMe();
    },
    [reloadMe],
  );

  const logout = useCallback(async () => {
    await api.POST("/api/v1/auth/logout").catch(() => undefined);
    tokenStore.set(null);
    setMe(null);
    setStatus("signed-out");
    queryClient.clear();
  }, [queryClient]);

  const can = useCallback((permission: string) => Boolean(me?.permissions.includes(permission)), [me]);

  return (
    <AuthContext.Provider value={{ status, me, can, login, verifyTwoFactor, reloadMe, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
