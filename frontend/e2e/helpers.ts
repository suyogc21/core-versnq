import { createHmac } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const OUTBOX = path.join(__dirname, ".state", "outbox");
export const CLIENT = (slug: string) => `http://${slug}.localhost:3100`;
export const STAFF = "http://admincore.localhost:3101";

/** The current 6-digit code for a base32 TOTP secret (what an authenticator app shows). */
export function totp(secret: string, at = Date.now()): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const bits = [...secret.replace(/=+$/, "")].map((c) => alphabet.indexOf(c).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const h = createHmac("sha1", key).update(counter).digest();
  const offset = h[19] & 15;
  return String((h.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

/** The token from the newest email sent to `to` (the API saves emails to the outbox). */
export async function tokenFromEmail(to: string): Promise<string> {
  let body: string | undefined;
  await expect
    .poll(() => {
      const mails = readdirSync(OUTBOX)
        .filter((f) => f.endsWith(".json")) // Core's own emails; campaign emails are .eml files
        .sort()
        .map((f) => JSON.parse(readFileSync(path.join(OUTBOX, f), "utf8")) as { to: string; body: string })
        .filter((m) => m.to === to);
      body = mails.at(-1)?.body;
      return Boolean(body);
    })
    .toBe(true);
  const token = body!.match(/token=([\w-]+)/)?.[1];
  if (!token) throw new Error(`No link in the email to ${to}`);
  return token;
}

export function codesSentTo(to: string): string[] {
  return readdirSync(OUTBOX)
    .filter((f) => f.endsWith(".json")) // Core's own emails; campaign emails are .eml files
    .sort()
    .map((f) => JSON.parse(readFileSync(path.join(OUTBOX, f), "utf8")) as { to: string; subject: string; body: string })
    .filter((m) => m.to === to && m.subject.includes("sign-in code"))
    .map((m) => m.body.match(/code is (\d{6})/)![1]);
}

/** Waits for a sign-in code email newer than the `before` codes already sent to `to`. */
export async function newCode(to: string, before: number): Promise<string> {
  await expect.poll(() => codesSentTo(to).length).toBeGreaterThan(before);
  return codesSentTo(to).at(-1)!;
}

/** Whether a company sign-in will ask for an emailed code (Decision #45): a new browser, and an
 * address that can receive mail (invented *.demo ones can't, so they get none). */
export const getsEmailCode = (url: string, email: string) => url !== STAFF && !email.endsWith(".demo");


/** Complete the "turn on two-factor" screen; returns the secret for later sign-ins. */
export async function turnOnTwoFactor(page: Page): Promise<string> {
  const field = page.getByLabel("6-digit code from the app");
  await expect(field).toBeVisible();
  const secret = (await page.locator("p.font-mono").innerText()).trim();
  await field.fill(totp(secret));
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByText("Two-factor authentication is on.")).toBeVisible();
  // The 10 backup codes are shown once (go-live G-4): confirm they were saved.
  const codes = page.getByTestId("backup-codes");
  await expect(codes.locator("li")).toHaveCount(10);
  await codes.getByLabel("I saved them").check();
  await codes.getByRole("button", { name: "Done" }).click();
  return secret;
}

/** Sign in from a fresh browser; enters the emailed code when the company asks for one. */
export async function signIn(page: Page, url: string, email: string, password: string) {
  const before = codesSentTo(email).length;
  await page.goto(`${url}/login`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (!getsEmailCode(url, email)) return;
  await expect(page.getByText("Check your email")).toBeVisible();
  await page.getByLabel("Code").fill(await newCode(email, before));
  await page.getByRole("button", { name: "Verify" }).click();
}
