import { expect, request, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * Step C1: a call reported by the phone app (here through the API) is on the lead's timeline
 * with its recording and the one-tap Outcome; it is in the Calls list too.
 */
test("a reported call shows on the lead with its recording and outcome", async ({ browser }) => {
  const { base, manager, call, ownerToken } = await companyWithTeams("proseware");
  const sources = (await call("GET", "/api/v1/lead-sources")) as { id: string; name: string }[];
  const lead = await call("POST", "/api/v1/leads", {
    first_name: "Kiran",
    identities: [{ type: "phone", value: "98444 55566", is_primary: true, is_whatsapp: false }],
    source_id: sources[0].id,
    owner_user_id: manager.id,
  });
  const reported = await call("POST", "/api/v1/calls", {
    external_id: "phone-call-1",
    direction: "out",
    status: "answered",
    number: "+91 98444 55566",
    started_at: new Date(Date.now() - 60_000).toISOString(),
    duration_seconds: 65,
  });
  const ctx = await request.newContext();
  const mp3 = Buffer.concat([Buffer.from("ID3\x04\x00\x00\x00\x00\x00\x00", "binary"), Buffer.alloc(4000)]);
  const up = await ctx.put(`${base}/api/v1/calls/${reported.call.id}/recording`, {
    headers: { Authorization: `Bearer ${ownerToken}`, "X-File-Name": "call.mp3", "Content-Type": "application/octet-stream" },
    data: mp3,
  });
  expect(up.status()).toBe(200);

  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();
  await expect // the signed-in app registers the service worker (installable app, C2)
    .poll(() => page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.active?.scriptURL ?? ""))
    .toContain("/sw.js");
  await page.goto(`${base}/leads/${lead.id}`);
  await expect(page.getByText("Outgoing call · 1m 05s")).toBeVisible();
  await page.getByRole("button", { name: "Play recording" }).click();
  await expect(page.locator("audio")).toBeVisible(); // fetched with the person's own sign-in
  await expect(page.getByTestId("call-outcome")).toBeVisible();

  await page.getByRole("complementary").getByRole("link", { name: "Calls" }).click();
  await expect(page.getByRole("link", { name: "Kiran" })).toBeVisible();
  await expect(page.getByText(/recorded/)).toBeVisible();
});
