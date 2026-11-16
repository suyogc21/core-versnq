import { expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * C13: someone who starts at ACE is sent to Core's /ace/open; signed out, they sign in first and
 * come back to /ace/open (here ACE's console isn't set up, so Core says so instead of leaving).
 */
test("starting at ACE: sign in to Core, then back to Open ACE", async ({ browser }) => {
  const { base, manager } = await companyWithTeams("adatum");
  const page = await (await browser.newContext()).newPage();
  await signIn(page, base, manager.email, manager.password, "/ace/open");
  await expect(page).toHaveURL(`${base}/ace/open`);
  await expect(page.getByText("ACE can't be opened")).toBeVisible();
});
