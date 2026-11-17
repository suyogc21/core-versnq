import { expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/** The dialer (Nov 17): My Day → Start calling goes through the rep's leads never contacted
 * (e.g. those pulled from LeadSquared). Inside the Android app the first call is placed at
 * once; after the outcome is logged the next follows a 5-second countdown, which Pause stops.
 * The app's phone part is stood in for here (it records the numbers it was asked to dial). */
test("Start calling places each call by itself, with Pause", async ({ browser }) => {
  test.setTimeout(90_000);
  const { base, manager, call } = await companyWithTeams("tailspin");
  const sources = (await call("GET", "/api/v1/lead-sources")) as { id: string }[];
  for (const [name, number] of [
    ["Anil", "98111 22233"],
    ["Bina", "98111 22244"],
  ]) {
    await call("POST", "/api/v1/leads", {
      first_name: name,
      identities: [{ type: "phone", value: number, is_primary: true, is_whatsapp: false }],
      source_id: sources[0].id,
      owner_user_id: manager.id,
    });
  }
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await page.addInitScript(() => {
    const w = window as unknown as { dialed: string[]; Capacitor: unknown };
    w.dialed = [];
    w.Capacitor = { Plugins: { VersnqPhone: { dial: async (o: { number: string }) => (w.dialed.push(o.number), { direct: true }) } } };
  });
  const dialed = () => page.evaluate(() => (window as unknown as { dialed: string[] }).dialed);
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("button", { name: "Start calling (2)" }).click();

  const bar = page.locator("[data-dialer]");
  await expect.poll(dialed).toHaveLength(1); // the first at once
  const [first] = await dialed();
  await expect(bar.getByText("Calling…")).toBeVisible();

  await page.getByRole("button", { name: "Interested", exact: true }).click();
  await page.getByRole("button", { name: "Tomorrow" }).click();
  await page.getByRole("button", { name: "Log call" }).click();
  await expect(bar.getByText(/Calling in \ds/)).toBeVisible(); // the next one, after a countdown
  await bar.getByRole("button", { name: "Pause" }).click();
  await page.waitForTimeout(6_000);
  expect(await dialed()).toHaveLength(1); // paused: nothing placed
  await bar.getByRole("button", { name: "Resume" }).click();
  await expect.poll(dialed, { timeout: 10_000 }).toHaveLength(2);
  const [, second] = await dialed();
  expect(new Set([first, second])).toEqual(new Set(["+919811122233", "+919811122244"]));
});
