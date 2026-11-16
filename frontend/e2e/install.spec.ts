import { expect, test } from "@playwright/test";

import { CLIENT } from "./helpers";

/** Step C2: the app can be installed (manifest, icons, service worker, offline page). */
test("the app is installable", async ({ request, page }) => {
  const base = CLIENT("anything");
  const manifest = await (await request.get(`${base}/manifest.webmanifest`)).json();
  expect(manifest.display).toBe("standalone");
  for (const icon of manifest.icons as { src: string }[]) {
    expect((await request.get(`${base}${icon.src}`)).headers()["content-type"]).toBe("image/png");
  }
  const sw = await request.get(`${base}/sw.js`);
  expect(sw.status()).toBe(200);
  expect(sw.headers()["cache-control"]).toContain("no-store");
  expect((await request.get(`${base}/offline.html`)).status()).toBe(200);


  await page.goto(`${base}/login`);
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
});
