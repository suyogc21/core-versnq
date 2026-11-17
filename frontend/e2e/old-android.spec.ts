import { devices, expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/** Older Android phones (Suyog's Android 9 phone: Chrome 101 engine, Nov 17). The browser is
 * made to behave like that engine: CSS.supports says no to translate and dvh, and the modern
 * properties do nothing, so only the fallbacks in globals.css can move and size things. The menu
 * starts hidden, opens, and its X closes it; a long dialog fits the screen and scrolls. */
test("on an older phone engine, the menu hides, opens and closes, and dialogs fit", async ({
  browser,
}) => {
  const { base, manager } = await companyWithTeams("oldphone");
  const ctx = await browser.newContext({ ...devices["Pixel 7"] });
  await ctx.addInitScript(() => {
    const real = CSS.supports.bind(CSS);
    CSS.supports = ((a: string, b?: string) =>
      a === "translate" || (a === "height" && String(b).includes("dvh"))
        ? false
        : b === undefined
          ? real(a)
          : real(a, b)) as typeof CSS.supports;
    document.addEventListener("DOMContentLoaded", () => {
      const s = document.createElement("style");
      s.textContent =
        "*,*::before,*::after{translate:none!important;rotate:none!important}";
      document.head.append(s);
    });
  });
  const page = await ctx.newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();
  expect(
    await page.evaluate(() =>
      document.documentElement.hasAttribute("data-no-translate"),
    ),
  ).toBe(true);

  const menu = page.locator("aside");
  await expect(menu).not.toBeInViewport(); // hidden at the start (it used to cover the page)
  await page.getByRole("button", { name: "Open menu" }).tap();
  await expect(menu).toBeInViewport();
  await page.getByRole("button", { name: "Close menu" }).tap();
  await expect(menu).not.toBeInViewport();

  await page.goto(`${base}/leads`);
  await page.getByRole("button", { name: /Add/ }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const view = page.viewportSize()!;
  const edges = async () => {
    const b = (await dialog.boundingBox())!;
    return {
      left: b.x >= 0,
      right: b.x + b.width <= view.width + 1,
      bottom: b.y + b.height <= view.height + 1,
    };
  };
  // after the 0.1 s opening animation: centred, not pushed off to the right; fits and scrolls inside
  await expect.poll(edges).toEqual({ left: true, right: true, bottom: true });
});
