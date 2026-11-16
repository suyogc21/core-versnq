import { devices, expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/** On a phone, the side menu opens, closes with its X and with a tap outside, and a link in it
 * navigates and closes it (reported from the Android app, Nov 16). */
test("the phone menu opens, closes and navigates", async ({ browser }) => {
  const { base, manager } = await companyWithTeams("fabrikam");
  const ctx = await browser.newContext({ ...devices["Pixel 7"] });
  const page = await ctx.newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();

  const menu = page.locator("aside");
  await page.getByRole("button", { name: "Open menu" }).tap();
  await expect(menu).toBeInViewport();
  await page.getByRole("button", { name: "Close menu" }).tap();
  await expect(menu).not.toBeInViewport();

  await page.getByRole("button", { name: "Open menu" }).tap();
  await expect(menu).toBeInViewport();
  await page.mouse.click(380, 400); // the dimmed page beside the menu
  await expect(menu).not.toBeInViewport();

  await page.getByRole("button", { name: "Open menu" }).tap(); // the Android app's back button
  expect(await page.evaluate(() => (window as unknown as { versnqBack: () => boolean }).versnqBack())).toBe(true);
  await expect(menu).not.toBeInViewport();
  expect(await page.evaluate(() => (window as unknown as { versnqBack: () => boolean }).versnqBack())).toBe(false);

  await page.getByRole("button", { name: "Open menu" }).tap();
  await menu.getByRole("link", { name: "Calls" }).tap();
  await expect(page).toHaveURL(/\/calls$/);
  await expect(menu).not.toBeInViewport();
});
