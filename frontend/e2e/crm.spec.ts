import { expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * Slice A: a rep adds a lead, logs a call (the follow-up rule refuses it without a next
 * follow-up), the follow-up shows on My Day; their manager sees the lead, a rep on another
 * team does not.
 */
test("a rep works a lead end to end, and visibility follows the team", async ({ browser }) => {
  const { base, manager, rep, otherRep } = await companyWithTeams("contoso");

  const page = await (await browser.newContext()).newPage();
  await signIn(page, base, rep.email, rep.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor(); // signed in
  await page.getByRole("link", { name: "Leads", exact: true }).click();
  await page.getByRole("button", { name: "Add lead" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("First name").fill("Zoya");
  await dialog.getByLabel("Last name").fill("Fernandes");
  await dialog.getByLabel("Phone").fill("98765 12345");
  await dialog.getByLabel("Source").selectOption({ label: "Referral" });
  await dialog.getByRole("button", { name: "Add lead" }).click();
  await expect(page.getByText("Lead added")).toBeVisible();

  // Phone-sized screens open the lead's own page; wide ones the side panel. Either way:
  const panel = page.locator("aside, main").filter({ hasText: "Zoya Fernandes" }).last();
  await expect(panel.getByText("+91 98765 12345")).toBeVisible();
  await panel.getByRole("button", { name: "Interested", exact: true }).click();
  await panel.getByRole("button", { name: "Log call" }).click();
  await expect(panel.getByText("Set the next follow-up")).toBeVisible(); // the anti-leakage rule

  await panel.getByRole("button", { name: "Tomorrow" }).click();
  await panel.getByRole("button", { name: "Log call" }).click();
  await expect(page.getByText("Call logged")).toBeVisible();
  await expect(panel.getByText("Call: Interested")).toBeVisible(); // on the timeline
  await expect(panel.getByText(/Next follow-up: Tomorrow/)).toBeVisible();

  await page.getByRole("link", { name: "My Day" }).click();
  await page.waitForURL(`${base}/`);
  await expect(page.getByRole("link", { name: /Zoya Fernandes/ })).toBeVisible(); // tomorrow's follow-up

  // The manager of Ravi's team sees the lead; Olga (another team) does not.
  const mgr = await (await browser.newContext()).newPage();
  await signIn(mgr, base, manager.email, manager.password);
  await mgr.getByRole("heading", { name: "My Day" }).waitFor(); // signed in
  await mgr.goto(`${base}/leads`);
  await mgr.getByPlaceholder("Search name, phone, email…").fill("Zoya");
  await expect(mgr.getByRole("cell", { name: /Zoya Fernandes/ })).toBeVisible();

  const other = await (await browser.newContext()).newPage();
  await signIn(other, base, otherRep.email, otherRep.password);
  await other.getByRole("heading", { name: "My Day" }).waitFor(); // signed in
  await other.goto(`${base}/leads`);
  await other.getByRole("button", { name: "All" }).click();
  await other.getByPlaceholder("Search name, phone, email…").fill("Zoya");
  await expect(other.getByText("No leads here.")).toBeVisible();
});
