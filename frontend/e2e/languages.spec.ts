import { devices, expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/** Batch 6: a person picks Arabic for their device in My account: the page turns right to left,
 * the menu and titles are in Arabic, and on a phone the menu still slides in and out (from the
 * right). Back to the company's language gives English again. */
test("Arabic: right to left, translated menu, phone menu still works", async ({ browser }) => {
  const { base, manager } = await companyWithTeams("lucerne");
  const ctx = await browser.newContext({ ...devices["Pixel 7"] });
  const page = await ctx.newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();

  await page.goto(`${base}/account`);
  await page.getByRole("combobox", { name: "Language" }).selectOption("ar");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "حسابي" })).toBeVisible();

  const menu = page.locator("aside");
  await expect(menu).not.toBeInViewport();
  await page.getByRole("button", { name: "فتح القائمة" }).tap();
  await expect(menu).toBeInViewport();
  const box = (await menu.boundingBox())!;
  expect(box.x).toBeGreaterThan(0); // on the right side of the screen
  await expect(menu.getByRole("link", { name: "يومي" })).toBeVisible();
  await page.getByRole("button", { name: "إغلاق القائمة" }).tap();
  await expect(menu).not.toBeInViewport();

  await page.reload(); // kept on this device
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByRole("combobox", { name: "اللغة" }).selectOption("");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.getByRole("heading", { name: "My account" })).toBeVisible();
});
