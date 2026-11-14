/** Build test data through the real API (the same calls the apps make). */
import { request, type APIRequestContext } from "@playwright/test";

import { E2E_STAFF_PASSWORD } from "../playwright.config";
import { CLIENT, codesSentTo, newCode, STAFF, tokenFromEmail, totp } from "./helpers";

type Json = Record<string, unknown>;

async function call(ctx: APIRequestContext, method: string, url: string, token?: string, data?: Json) {
  const res = await ctx.fetch(url, {
    method,
    data,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok()) throw new Error(`${method} ${url} -> ${res.status()} ${await res.text()}`);
  return res.status() === 204 ? null : res.json();
}

const tokens = new Map<string, string>(); // one sign-in per account per test run

/** Sign in (staff: turning on 2FA the first time; company people: the emailed code). Returns an access token. */
async function signInWith2fa(ctx: APIRequestContext, base: string, prefix: string, email: string, password: string) {
  const known = tokens.get(email);
  if (known) return known;
  const token = await firstSignIn(ctx, base, prefix, email, password);
  tokens.set(email, token);
  return token;
}

async function firstSignIn(ctx: APIRequestContext, base: string, prefix: string, email: string, password: string) {
  const before = codesSentTo(email).length;
  let login = await call(ctx, "POST", `${base}${prefix}/auth/login`, undefined, { email, password });
  if (login.two_factor_method === "email") {
    const code = await newCode(email, before);
    login = await call(ctx, "POST", `${base}${prefix}/auth/2fa/verify`, undefined, { challenge_token: login.challenge_token, code });
  }
  if (login.access_token) {
    const me = await call(ctx, "GET", `${base}${prefix}/auth/me`, login.access_token);
    if (!me.restrictions.includes("two_factor_setup_required")) return login.access_token as string;
    const setup = await call(ctx, "POST", `${base}${prefix}/auth/2fa/setup`, login.access_token);
    await call(ctx, "POST", `${base}${prefix}/auth/2fa/enable`, login.access_token, { code: totp(setup.secret) });
    return login.access_token as string;
  }
  throw new Error(`${email} already has 2FA from an earlier run; the e2e database is rebuilt per run`);
}

export type Person = { email: string; password: string; id: string };

/** A company with an Owner, a manager with one rep, and a rep on another team. */
export async function companyWithTeams(slug: string) {
  const staffCtx = await request.newContext();
  const staff = await signInWith2fa(staffCtx, STAFF, "/platform", "e2e-api@versnq.in", E2E_STAFF_PASSWORD);
  const ownerEmail = `owner@${slug}.example.org`;
  await call(staffCtx, "POST", `${STAFF}/platform/tenants`, staff, {
    name: `${slug} Ltd`,
    slug,
    industry_pack: "generic",
    timezone: "Asia/Kolkata",
    default_country: "IN",
    owner_name: "Oscar Owner",
    owner_email: ownerEmail,
  });

  const ctx = await request.newContext();
  const base = CLIENT(slug);
  const join = async (email: string, password: string) => {
    await call(ctx, "POST", `${base}/api/v1/auth/invite/accept`, undefined, { token: await tokenFromEmail(email), password });
  };
  await join(ownerEmail, "owner-password-123");
  const owner = await signInWith2fa(ctx, base, "/api/v1", ownerEmail, "owner-password-123");

  const roles = await call(ctx, "GET", `${base}/api/v1/roles`, owner);
  const roleId = (key: string) => roles.find((r: Json) => r.key === key).id as string;
  const person = async (name: string, key: string): Promise<Person> => {
    const email = `${name.toLowerCase()}@${slug}.example.org`;
    const password = `${name.toLowerCase()}-password-1`;
    const user = await call(ctx, "POST", `${base}/api/v1/users`, owner, { name, email, role_id: roleId(key) });
    await join(email, password); // no API sign-in: sign-ins are rate-limited per address
    return { email, password, id: user.id };
  };
  const manager = await person("Maya", "sales_manager");
  const rep = await person("Ravi", "sales_user");
  const otherRep = await person("Olga", "sales_user");
  const team = await call(ctx, "POST", `${base}/api/v1/teams`, owner, { name: "North" });
  await call(ctx, "PUT", `${base}/api/v1/teams/${team.id}/members`, owner, [
    { user_id: manager.id, is_manager: true },
    { user_id: rep.id, is_manager: false },
  ] as unknown as Json);
  return { base, manager, rep, otherRep, ownerToken: owner, call: (method: string, path: string, data?: Json) => call(ctx, method, `${base}${path}`, owner, data) };
}
