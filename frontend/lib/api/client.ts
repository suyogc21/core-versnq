import createClient from "openapi-fetch";
import type { paths } from "./schema";

/**
 * The access token lives only in memory (never localStorage). The refresh token is an
 * httpOnly cookie the browser sends to /api/v1/auth automatically; we never see it.
 */
let accessToken: string | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (token: string | null) => {
    accessToken = token;
  },
};

let refreshing: Promise<boolean> | null = null;

/** One shared refresh at a time; resolves true when a new access token was stored. */
export function refreshAccessToken(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh", { method: "POST" });
      const body = res.ok ? await res.json() : null;
      tokenStore.set(body?.access_token ?? null);
      return Boolean(body?.access_token);
    } catch {
      tokenStore.set(null);
      return false;
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function authFetch(request: Request): Promise<Response> {
  const send = () => {
    const req = request.clone();
    const token = tokenStore.get();
    if (token) req.headers.set("Authorization", `Bearer ${token}`);
    return fetch(req);
  };
  const res = await send();
  if (res.status !== 401 || new URL(request.url).pathname.startsWith("/api/v1/auth/")) {
    return res;
  }
  return (await refreshAccessToken()) ? send() : res;
}

export const api = createClient<paths>({ baseUrl: "", fetch: authFetch });
