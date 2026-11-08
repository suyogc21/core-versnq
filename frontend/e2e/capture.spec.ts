import { expect, request, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * Step 1: a website posts an enquiry → the assignment rule gives it to the rep → the rep is
 * notified and opens it; the manager imports a CSV with a repeat and a bad row and gets the
 * problem rows back.
 */
test("leads arrive from a web form and a CSV import, routed and de-duplicated", async ({ browser }) => {
  const { base, manager, rep, call } = await companyWithTeams("fabrikam");
  await call("POST", "/api/v1/assignment-rules", { name: "All to Ravi", strategy: "user", user_ids: [rep.id], conditions: [], is_active: true });
  const sources = (await call("GET", "/api/v1/lead-sources")) as { id: string; name: string }[];
  const website = sources.find((s) => s.name === "Website")!.id;
  const form = await call("POST", "/api/v1/capture-sources", { name: "Site form", source_id: website, is_active: true, field_map: {} });

  const site = await request.newContext();
  const posted = await site.post(`${base}/api/v1/capture/${form.key}`, {
    data: { name: "Web Visitor", phone: "98222 33344", message: "Call me", consent_email: "yes" },
  });
  expect(posted.status()).toBe(202);

  // The rep is told, and opens the lead from the bell.
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await signIn(page, base, rep.email, rep.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();
  await page.getByRole("button", { name: /Notifications, 1 unread/ }).first().click();
  await page.getByRole("button", { name: /New lead: Web Visitor/ }).click();
  await expect(page.getByText("Added via the Site form form")).toBeVisible();
  await expect(page.getByText("Opted in", { exact: true })).toBeVisible();

  // The manager imports a file: one new, one repeat of the web lead, one without contact.
  const mgr = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await signIn(mgr, base, manager.email, manager.password);
  await mgr.getByRole("heading", { name: "My Day" }).waitFor();
  await mgr.goto(`${base}/leads/import`);
  await mgr.getByLabel("CSV file").setInputFiles({
    name: "fair.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Name,Mobile,City\nAsha Rao,98222 55566,Pune\nWeb Visitor,+91 98222-33344,Goa\nNo Contact,,Pune\n"),
  });
  await expect(mgr.getByText("3 rows")).toBeVisible();
  await mgr.locator("#imp-source").selectOption({ label: "Referral" });
  await mgr.getByRole("button", { name: "Import 3 rows" }).click();
  await expect(mgr.getByText("Finished")).toBeVisible({ timeout: 90_000 });
  await expect(mgr.getByRole("button", { name: /Download the 1 rows not imported/ })).toBeVisible();
});
