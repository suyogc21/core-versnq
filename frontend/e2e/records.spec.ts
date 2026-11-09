import { expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * Step 2: an admin-defined record type (Property) gets its own list; a manager adds one and
 * links a lead to it from the lead's page; the link shows on both records; a rep on another
 * team cannot see that manager's property.
 */
test("company-defined records with links, access per role", async ({ browser }) => {
  const { base, manager, otherRep, call } = await companyWithTeams("tailspin");
  const rt = await call("POST", "/api/v1/record-types", { key: "property", singular: "Property", plural: "Properties", has_owner: true, has_stages: false });
  await call("POST", "/api/v1/custom-fields?entity=rt:property", { key: "price", label: "Price", type: "number", options: [], required: false, is_unique: false });
  await call("POST", "/api/v1/link-types", { to_type_id: rt.id, label: "Interested in", inverse_label: "Interested buyers", many_to: true, many_from: true });
  const sources = (await call("GET", "/api/v1/lead-sources")) as { id: string; name: string }[];
  const lead = await call("POST", "/api/v1/leads", {
    first_name: "Nadia",
    identities: [{ type: "phone", value: "98333 44455", is_primary: true, is_whatsapp: false }],
    source_id: sources[0].id,
    owner_user_id: manager.id,
  });

  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();
  await page.getByRole("complementary").getByRole("link", { name: "Properties" }).click();
  await page.getByRole("button", { name: "Add property" }).click();
  await page.getByLabel("Name").fill("Villa 21");
  await page.getByLabel("Price").fill("2500000");
  await page.getByRole("button", { name: "Add property" }).last().click();
  await expect(page.getByRole("heading", { name: "Villa 21" })).toBeVisible();

  await page.goto(`${base}/leads/${lead.id}`);
  await page.getByRole("button", { name: "Link", exact: true }).click();
  await page.getByLabel("Search to link").fill("Villa");
  await page.getByRole("button", { name: "Villa 21" }).click();
  await expect(page.getByText("Interested in: Villa 21")).toBeVisible(); // lead timeline
  await page.getByRole("link", { name: "Villa 21" }).click();
  await expect(page.getByText("Interested buyers · 1")).toBeVisible();
  await expect(page.getByRole("link", { name: "Nadia" })).toBeVisible();

  const other = await (await browser.newContext()).newPage();
  await signIn(other, base, otherRep.email, otherRep.password);
  await other.getByRole("heading", { name: "My Day" }).waitFor();
  await other.goto(`${base}/r/property`);
  await expect(other.getByText("No properties yet.")).toBeVisible();
});
