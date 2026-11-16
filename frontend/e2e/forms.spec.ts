import { expect, request, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * Real forms (Nov 16): a manager builds a form in Settings, its page opens on a phone, a visitor
 * sends it, and the lead arrives. The page may be embedded on other sites; sign-in pages may not.
 */
test("build a form, share its link, a visitor sends it from a phone", async ({ browser }) => {
  const { base, manager, call } = await companyWithTeams("wingtip");
  const roles = (await call("GET", "/api/v1/roles")) as { id: string; key: string; permissions: string[] }[];
  const mgrRole = roles.find((r) => r.key === "sales_manager")!;
  await call("PATCH", `/api/v1/roles/${mgrRole.id}`, { permissions: [...mgrRole.permissions, "crm.configure"] });

  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();
  await page.goto(`${base}/settings/lead-capture`);
  await page.getByRole("button", { name: "Add a form" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Free demo");
  await page.getByLabel("Source").selectOption({ label: "Website" });
  await page.getByLabel("Title", { exact: true }).fill("Book a free demo");
  await page.getByRole("button", { name: "Create form" }).click();
  await expect(page.getByRole("button", { name: "Copy link" })).toBeVisible();

  const forms = (await call("GET", "/api/v1/capture-sources")) as { name: string; public_id: string }[];
  const link = `${base}/f/${forms.find((f) => f.name === "Free demo")!.public_id}`;
  const headers = (await (await request.newContext()).get(link)).headers();
  expect(headers["x-frame-options"]).toBeUndefined();
  expect(headers["content-security-policy"]).toContain("frame-ancestors *");

  const phone = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await phone.goto(`${link}?utm_source=whatsapp`);
  await expect(phone.getByRole("heading", { name: "Book a free demo" })).toBeVisible();
  await phone.getByRole("button", { name: "Send" }).click();
  await expect(phone.getByText("Please fill this in").first()).toBeVisible(); // name and phone are required
  await phone.getByLabel("Your name").fill("Priya Nair");
  await phone.getByLabel("Phone").fill("98111 22233");
  await phone.getByRole("button", { name: "Send" }).click();
  await expect(phone.getByText("Thank you. We'll be in touch soon.")).toBeVisible();

  const leads = (await call("GET", "/api/v1/leads?q=Priya")) as { items: { first_name: string; utm_source: string | null }[] };
  expect(leads.items.map((l) => l.first_name)).toEqual(["Priya"]);
});
