import { expect, test } from "@playwright/test";

import { E2E_STAFF_PASSWORD } from "../playwright.config";
import { CLIENT, signIn, STAFF, tokenFromEmail, turnOnTwoFactor } from "./helpers";

/**
 * Gate 1 (roadmap 1.17): staff creates a company → the Owner accepts the invite, sets a
 * password and signs in → the Owner invites a Sales User → the Sales User signs in and
 * sees only the screens their role allows, and the admin pages refuse them.
 */
const SLUG = "northwind";
const OWNER = { name: "Olivia Owner", email: "olivia@northwind.demo", password: "owner-password-123" };
const SELLER = { name: "Sam Seller", email: "sam@northwind.demo", password: "seller-password-123" };

test("a new company goes from creation to a working, permission-limited team", async ({ browser }) => {
  // 1. Versnq staff signs in (first time: 2FA setup) and creates the company.
  const staff = await (await browser.newContext()).newPage();
  await signIn(staff, STAFF, "e2e-staff@versnq.in", E2E_STAFF_PASSWORD);
  await turnOnTwoFactor(staff);
  await expect(staff.getByRole("button", { name: "Backup codes: 10 left" })).toBeVisible();
  await staff.getByRole("button", { name: "Create company" }).click();
  await staff.getByLabel("Company name").fill("Northwind Learning");
  await staff.getByLabel("Address").fill(SLUG);
  await staff.getByLabel("Industry pack").selectOption({ label: "EdTech" });
  await staff.getByLabel("Owner name").fill(OWNER.name);
  await staff.getByLabel("Owner email").fill(OWNER.email);
  await staff.getByRole("button", { name: "Create and invite Owner" }).click();
  await expect(staff.getByRole("heading", { name: "Northwind Learning" })).toBeVisible();
  await expect(staff.getByText("tenant.created")).toBeVisible();

  // 2. The Owner follows the emailed invite, sets a password and signs in (2FA is optional, #45).
  const owner = await (await browser.newContext()).newPage();
  await owner.goto(`${CLIENT(SLUG)}/invite?token=${await tokenFromEmail(OWNER.email)}`);
  await owner.getByLabel("New password").fill(OWNER.password);
  await owner.getByLabel("Repeat password").fill(OWNER.password);
  await owner.getByRole("button", { name: "Set password and continue" }).click();
  await expect(owner).toHaveURL(/\/login$/);
  await signIn(owner, CLIENT(SLUG), OWNER.email, OWNER.password);
  await expect(owner.locator("aside").getByText("Northwind Learning")).toBeVisible();
  // Everything set up once lives under one Settings entry, grouped on its home page.
  await owner.getByRole("complementary").getByRole("link", { name: "Settings", exact: true }).click();
  for (const item of ["Company", "Users", "Teams", "Roles", "Records and fields", "Lead capture", "Audit log"]) {
    await expect(owner.getByRole("link", { name: new RegExp(`^${item}`) })).toBeVisible();
  }

  // 3. The Owner invites a Sales User.
  await owner.getByRole("link", { name: /^Users/ }).click();
  await owner.getByRole("button", { name: "Invite user" }).click();
  await owner.getByLabel("Name").fill(SELLER.name);
  await owner.getByLabel("Work email").fill(SELLER.email);
  await owner.getByLabel("Role").selectOption({ label: "Sales User" });
  await owner.getByRole("button", { name: "Send invite" }).click();
  await expect(owner.getByRole("cell", { name: SELLER.email })).toBeVisible();

  // 4. The Sales User joins and sees only what their role allows.
  const seller = await (await browser.newContext()).newPage();
  await seller.goto(`${CLIENT(SLUG)}/invite?token=${await tokenFromEmail(SELLER.email)}`);
  await seller.getByLabel("New password").fill(SELLER.password);
  await seller.getByLabel("Repeat password").fill(SELLER.password);
  await seller.getByRole("button", { name: "Set password and continue" }).click();
  await expect(seller).toHaveURL(/\/login$/);
  await signIn(seller, CLIENT(SLUG), SELLER.email, SELLER.password);
  await expect(seller.getByRole("heading", { name: /Good to see you, Sam/ })).toBeVisible();
  // EdTech pack labels reach the screen: leads are "Students".
  await expect(seller.getByRole("link", { name: "Students", exact: true })).toBeVisible();
  await expect(seller.getByText("New students", { exact: true })).toBeVisible();
  await expect(seller.getByRole("link", { name: "Settings", exact: true })).toHaveCount(0);
  // Typing an admin address directly gets a refusal, not an empty admin page.
  for (const page of ["settings", "settings/users", "settings/roles", "settings/company", "settings/records"]) {
    await seller.goto(`${CLIENT(SLUG)}/${page}`);
    await expect(seller.getByText("You don't have permission to do that.")).toBeVisible();
    await expect(seller.getByRole("button", { name: /Invite user|New role|Save settings/ })).toHaveCount(0);
  }

  // 5. The Owner's audit log recorded the invite.
  await owner.getByRole("complementary").getByRole("link", { name: "Settings", exact: true }).click();
  await owner.getByRole("link", { name: /^Audit log/ }).click();
  await expect(owner.getByText("user.invited")).toBeVisible();
});

test("a workspace address that does not exist shows nothing", async ({ page }) => {
  await page.goto(`${CLIENT("no-such-company")}/login`);
  await page.getByLabel("Email").fill("anyone@example.com");
  await page.getByLabel("Password", { exact: true }).fill("whatever-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Workspace not found")).toBeVisible();
});

test("sign-in pages refuse to be embedded in other sites", async ({ request }) => {
  for (const url of [`${CLIENT("anything")}/login`, `${STAFF}/login`]) {
    const res = await request.get(url);
    expect(res.headers()["x-frame-options"]).toBe("DENY");
    expect(res.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  }
});
