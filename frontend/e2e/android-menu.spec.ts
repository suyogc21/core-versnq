import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";

import { expect, test } from "@playwright/test";
import { _android as android } from "playwright-core";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/** Inside the real Android app (an emulator or a phone on adb, ANDROID_E2E=1): the side menu's
 * Close (X) button closes it when tapped with a real Android touch, not only in a phone-sized
 * browser (Suyog, Nov 17: the X did nothing in the app). The app's WebView is pointed at the
 * local test stack through adb reverse. */
test.skip(
  !process.env.ANDROID_E2E,
  "needs an Android emulator or phone on adb",
);

test("in the Android app, the menu's X closes the menu", async () => {
  test.setTimeout(240_000);
  const { base, manager } = await companyWithTeams("glacier");
  execSync("adb reverse tcp:3100 tcp:3100");
  const [device] = await android.devices();
  await device.shell("am force-stop in.versnq.core");
  await device.shell("am start -n in.versnq.core/.MainActivity");
  const page = await (await device.webView({ pkg: "in.versnq.core" })).page();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("heading", { name: "My Day" }).waitFor();

  // A real Android touch (adb input tap) at the middle of an element: where the WebView sits on
  // screen (from the UI dump) + the element's CSS position × the device pixel ratio.
  const dump = (
    await device.shell(
      "uiautomator dump /sdcard/ui.xml >/dev/null && cat /sdcard/ui.xml",
    )
  ).toString();
  const [, left, top] = dump
    .match(/class="android\.webkit\.WebView"[^>]*bounds="\[(\d+),(\d+)\]/)!
    .map(Number);
  const touch = async (selector: string) => {
    const [x, y] = await page.evaluate((sel) => {
      const b = document.querySelector(sel)!.getBoundingClientRect();
      return [
        (b.x + b.width / 2) * devicePixelRatio,
        (b.y + b.height / 2) * devicePixelRatio,
      ];
    }, selector);
    await device.shell(
      `input tap ${Math.round(left + x)} ${Math.round(top + y)}`,
    );
  };
  const menuX = () =>
    page.evaluate(
      () => document.querySelector("aside")!.getBoundingClientRect().x,
    );
  await page.goto(`${base}/leads`); // where Suyog's screenshot was taken
  await page.getByRole("heading", { name: "Leads" }).waitFor();
  await touch('button[aria-label="Open menu"]');
  await expect.poll(menuX).toBe(0);

  const info = await page.evaluate(() => {
    const b = document
      .querySelector('button[aria-label="Close menu"]')!
      .getBoundingClientRect();
    const hit = document.elementFromPoint(
      b.x + b.width / 2,
      b.y + b.height / 2,
    );
    return {
      box: [b.x, b.y, b.width, b.height],
      hit: hit?.outerHTML.slice(0, 160),
      dpr: devicePixelRatio,
    };
  });
  console.log("close button", JSON.stringify(info), "webview at", left, top);
  if (process.env.ANDROID_SHOT)
    writeFileSync(process.env.ANDROID_SHOT, await device.screenshot());
  await touch('button[aria-label="Close menu"]');
  await expect.poll(menuX, { timeout: 5_000 }).toBeLessThan(0);
  await device.close();
});
