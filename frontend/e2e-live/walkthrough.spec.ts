import {
  devices,
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { totp } from "../e2e/helpers";

/** The walk-through on the live server (docs/walkthrough.md), in the test company. Each area is a
 * step with soft checks, so one failure doesn't hide the others; the report lists them all. */
const SLUG = process.env.WT_SLUG ?? "walkthrough";
const BASE = `https://${SLUG}.core.versnq.in`;
const EMAIL = process.env.WT_EMAIL!;
const PASSWORD = process.env.WT_PASSWORD!;
const SECRET = process.env.WT_TOTP!;
// Fresh values each run, so a re-run never collides with what an earlier run made.
const RUN = String(Date.now()).slice(-5);
const PHONE = (n: number) =>
  `98${(10000000 + Number(RUN) * 10 + n).toString().slice(-8)}`;
const MP3 = Buffer.concat([
  Buffer.from("ID3\x04\x00\x00\x00\x00\x00\x00", "binary"),
  Buffer.alloc(2000),
]);

const PAGES = [
  "/",
  "/account",
  "/calls",
  "/calls/unknown",
  "/customers",
  "/dashboards",
  "/deals",
  "/inbox",
  "/key-accounts",
  "/landing-pages",
  "/leads",
  "/leads/import",
  "/money",
  "/newsletters",
  "/outreach",
  "/reports",
  "/sequences",
  "/settings",
  "/settings/audit",
  "/settings/automations",
  "/settings/brands",
  "/settings/calls",
  "/settings/company",
  "/settings/crm",
  "/settings/developers",
  "/settings/inboxes",
  "/settings/lead-ads",
  "/settings/lead-capture",
  "/settings/money",
  "/settings/records",
  "/settings/records/customer",
  "/settings/records/deal",
  "/settings/records/lead",
  "/settings/records/tags",
  "/settings/reply-categories",
  "/settings/roles",
  "/settings/security",
  "/settings/sms",
  "/settings/teams",
  "/settings/users",
  "/settings/whatsapp",
];

async function api(
  ctx: APIRequestContext,
  token: string,
  method: string,
  path: string,
  data?: unknown,
) {
  const r = await ctx.fetch(`${BASE}/api/v1${path}`, {
    method,
    data,
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = r.status() === 204 ? null : await r.json().catch(() => null);
  return { status: r.status(), body };
}

async function freshCode() {
  // a code with at least 8 seconds left, so it isn't stale when it arrives
  if (Date.now() % 30_000 > 22_000)
    await new Promise((r) =>
      setTimeout(r, 30_000 - (Date.now() % 30_000) + 500),
    );
  return totp(SECRET);
}

async function apiToken(ctx: APIRequestContext) {
  const login = await (
    await ctx.post(`${BASE}/api/v1/auth/login`, {
      data: { email: EMAIL, password: PASSWORD },
    })
  ).json();
  if (login.access_token) return login.access_token as string;
  const v = await ctx.post(`${BASE}/api/v1/auth/2fa/verify`, {
    data: { challenge_token: login.challenge_token, code: await freshCode() },
  });
  return (await v.json()).access_token as string;
}

async function signIn(page: Page) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByLabel("Code").fill(await freshCode());
  await page.getByRole("button", { name: /Verify|Continue|Sign in/ }).click();
  await page
    .getByRole("heading", { name: "My Day" })
    .waitFor({ timeout: 30_000 });
}

/** Opens a page and reports what's wrong: an error screen, browser errors, sideways scroll. */
async function check(page: Page, path: string, phone: boolean) {
  const errors: string[] = [];
  const onError = (e: Error) => errors.push(e.message);
  page.on("pageerror", onError);
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState("networkidle").catch(() => {});
  const crashed = await page
    .getByText(/Something went wrong|Application error/i)
    .count();
  const sideways = phone
    ? await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      )
    : 0;
  page.off("pageerror", onError);
  return { path, crashed: crashed > 0, errors, sideways };
}

test("walk-through on the live server", async ({ browser, playwright }) => {
  const ctx = await playwright.request.newContext();
  const token = await apiToken(ctx);
  const results: Record<string, string> = {};
  const note = (area: string, ok: boolean, detail = "") => {
    results[area] = `${ok ? "PASS" : "FAIL"}${detail ? ` — ${detail}` : ""}`;
    expect.soft(ok, `${area}: ${detail}`).toBe(true);
  };

  await test.step("1-sign-in and every screen (laptop)", async () => {
    const page = await (await browser.newContext()).newPage();
    await signIn(page);
    const bad = [];
    for (const p of PAGES) {
      const r = await check(page, p, false);
      if (r.crashed || r.errors.length)
        bad.push(
          `${p} ${r.crashed ? "crashed" : ""} ${r.errors.join("; ").slice(0, 120)}`,
        );
    }
    note("01 sign-in with 2FA app", true);
    note(
      "screens (laptop): all load without errors",
      bad.length === 0,
      bad.join(" | "),
    );
  });

  await test.step("24-every screen at phone width", async () => {
    const page = await (
      await browser.newContext({ ...devices["Pixel 7"] })
    ).newPage();
    await signIn(page);
    const bad = [];
    for (const p of PAGES) {
      const r = await check(page, p, true);
      if (r.crashed || r.errors.length || r.sideways > 2)
        bad.push(
          `${p}${r.crashed ? " crashed" : ""}${r.sideways > 2 ? ` sideways ${r.sideways}px` : ""} ${r.errors.join("; ").slice(0, 100)}`,
        );
    }
    note(
      "24 phone layout: no crash, no errors, no sideways scroll",
      bad.length === 0,
      bad.join(" | "),
    );
    const menu = page.locator("aside");
    const right = () => menu.evaluate((el) => el.getBoundingClientRect().right);
    await page.goto(`${BASE}/leads`);
    await page.getByRole("button", { name: "Open menu" }).tap();
    await expect.poll(right).toBeGreaterThan(100);
    await page.getByRole("button", { name: "Close menu" }).tap();
    await expect
      .poll(right)
      .toBeLessThanOrEqual(0)
      .catch(() => {});
    note(
      "24 phone menu opens and its X closes it",
      (await right()) <= 0,
      `menu right edge ${await right()}`,
    );
  });

  // ---------- the main journeys, through the API the screens use ----------
  const sources = (await api(ctx, token, "GET", "/lead-sources")).body as {
    id: string;
    name: string;
  }[];
  const source = sources.find((s) => s.name === "Website") ?? sources[0];
  let leadId = "";

  await test.step("4-leads", async () => {
    const r = await api(ctx, token, "POST", "/leads", {
      first_name: "Walk",
      last_name: "Test",
      identities: [{ type: "phone", value: PHONE(1) }],
      source_id: source.id,
    });
    leadId = r.body?.id;
    const dup = await api(ctx, token, "POST", "/leads", {
      first_name: "Again",
      identities: [{ type: "phone", value: PHONE(1) }],
      source_id: source.id,
    });
    note("04 add a lead", r.status === 201, `status ${r.status}`);
    note(
      "04 duplicate warning on the same phone",
      dup.status === 409 || dup.status === 422,
      `status ${dup.status}`,
    );
  });

  await test.step("6/7-forms and landing pages", async () => {
    const form = {
      title: "Walkthrough form",
      button: "Send",
      fields: [
        { target: "full_name", label: "Name", required: true },
        { target: "phone", label: "Mobile", required: true },
      ],
    };
    const cs = await api(ctx, token, "POST", "/capture-sources", {
      name: `Walkthrough form ${RUN}`,
      source_id: source.id,
      form,
      hosted: true,
    });
    const id = cs.body?.public_id;
    const hosted = await ctx.get(`${BASE}/f/${id}`);
    const sent = await ctx.post(`${BASE}/api/v1/forms/${id}`, {
      data: { full_name: "Form Person", phone: PHONE(2) },
    });
    note(
      "06 form: hosted page and a submission makes a lead",
      cs.status === 201 && hosted.status() === 200 && sent.status() === 201,
      `create ${cs.status}, page ${hosted.status()}, send ${sent.status()}`,
    );
    const lp = await api(ctx, token, "POST", "/landing-pages", {
      title: "Walkthrough page",
      slug: `walkthrough-page-${RUN}`,
      published: true,
      blocks: [
        { type: "heading", text: "Hello", level: 1 },
        { type: "form", form_id: id },
      ],
    });
    const pub = await ctx.get(`${BASE}/p/walkthrough-page-${RUN}`);
    note(
      "07 landing page published at /p/…",
      lp.status === 201 && pub.status() === 200,
      `create ${lp.status}, page ${pub.status()}`,
    );
  });

  await test.step("9/10/11-deal, customer, invoice, payment", async () => {
    const pipeline = ((await api(ctx, token, "GET", "/pipelines")).body ??
      [])[0];
    const deal = await api(ctx, token, "POST", "/deals", {
      lead_id: leadId,
      pipeline_id: pipeline?.id,
    });
    note("09 deal on the lead", deal.status === 201, `status ${deal.status}`);
    const cust = await api(ctx, token, "POST", `/leads/${leadId}/customer`, {});
    note(
      "10 convert to customer",
      cust.status === 201,
      `status ${cust.status}`,
    );
    const inv = await api(ctx, token, "POST", "/invoices", {
      customer_id: cust.body?.id,
    });
    const rates = ((await api(ctx, token, "GET", "/money/tax-rates")).body ??
      []) as { id: string; name: string }[];
    const gst = rates.find((r) => r.name.includes("18"));
    const lines = [
      {
        description: "Walkthrough fee",
        quantity: 1,
        unit_price_minor: 100_000,
        tax_rate_id: gst?.id,
      },
    ];
    const draft = await api(ctx, token, "PATCH", `/invoices/${inv.body?.id}`, {
      version: inv.body?.version,
      lines,
    });
    const issued = await api(
      ctx,
      token,
      "POST",
      `/invoices/${inv.body?.id}/issue`,
      {},
    );
    const total = issued.body?.total_minor;
    const pay = await ctx.post(
      `${BASE}/api/v1/invoices/${inv.body?.id}/payments?amount_minor=${total}&method=bank&name=proof.pdf&paid_on=${new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })}`,
      {
        data: Buffer.from("%PDF-1.4\n" + "x".repeat(200)),
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/octet-stream",
        },
      },
    );
    const after = await api(ctx, token, "GET", `/invoices/${inv.body?.id}`);
    note(
      "11 invoice with 18% GST, issued, paid in full",
      inv.status === 201 &&
        draft.status === 200 &&
        issued.status === 200 &&
        total === 118_000 &&
        pay.status() < 300 &&
        after.body?.paid_minor === total &&
        after.body?.status === "paid",
      `create ${inv.status}, lines ${draft.status}, issue ${issued.status}, total ${total}, pay ${pay.status()}, paid ${after.body?.paid_minor}, status ${after.body?.status}`,
    );
  });

  await test.step("16-calls from the phone app, with a recording", async () => {
    const dev = await api(ctx, token, "POST", "/phone/devices", {
      install_id: `walkthrough-${Date.now()}`,
      device: "walkthrough",
      version: "0.5.1",
    });
    const key = dev.body?.token as string;
    const call = await ctx.post(`${BASE}/api/v1/calls`, {
      headers: { Authorization: `Bearer ${key}` },
      data: {
        external_id: `wt-${Date.now()}`,
        direction: "out",
        status: "answered",
        number: PHONE(1),
        started_at: new Date().toISOString(),
        duration_seconds: 75,
      },
    });
    const c = (await call.json()).call;
    const up = await ctx.put(`${BASE}/api/v1/calls/${c?.id}/recording`, {
      data: MP3,
      headers: { Authorization: `Bearer ${key}`, "X-File-Name": "call.mp3" },
    });
    const play = await ctx.get(`${BASE}/api/v1/calls/${c?.id}/recording`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    note(
      "16/17 phone key reports a call on the lead, recording uploads and plays",
      dev.status === 201 &&
        call.status() === 200 &&
        c?.lead_id === leadId &&
        up.status() === 200 &&
        play.status() === 200,
      `connect ${dev.status}, call ${call.status()}, on lead ${c?.lead_id === leadId}, upload ${up.status()}, play ${play.status()}`,
    );
    const apk = await ctx.head(`${BASE}/app/versnq-core.apk`);
    note(
      "17 app download link",
      apk.status() === 200,
      `status ${apk.status()}`,
    );
  });

  await test.step("18-custom report", async () => {
    const run = await api(ctx, token, "POST", "/reports/run", {
      source: "leads",
      group_by: ["source"],
      display: "bar",
    });
    note("18 custom report runs", run.status === 200, `status ${run.status}`);
  });

  await test.step("20-developers", async () => {
    const roles = ((await api(ctx, token, "GET", "/roles")).body ?? []) as {
      id: string;
      key: string;
    }[];
    const key = await api(ctx, token, "POST", "/integrations/keys", {
      name: `Walkthrough key ${RUN}`,
      role_id: roles.find((r) => r.key === "admin")?.id,
    });
    const use = key.body?.key
      ? await ctx.get(`${BASE}/api/v1/leads`, {
          headers: { Authorization: `Bearer ${key.body.key}` },
        })
      : null;
    note(
      "20 API key made and works",
      key.status === 201 && use?.status() === 200,
      `make ${key.status}, use ${use?.status()}`,
    );
  });

  await test.step("22-data protection", async () => {
    const pd = await api(ctx, token, "GET", `/leads/${leadId}/personal-data`);
    note("22 a person's data", pd.status === 200, `status ${pd.status}`);
    const ex = await api(ctx, token, "POST", "/data-exports");
    let ready = false;
    for (let i = 0; i < 24 && ex.status === 201; i++) {
      const list = (await api(ctx, token, "GET", "/data-exports")).body as {
        id: string;
        status: string;
      }[];
      if (list?.find((x) => x.id === ex.body.id)?.status === "ready") {
        ready = true;
        break;
      }
      await new Promise((r) => setTimeout(r, 5000));
    }
    const dl = ready
      ? await ctx.get(`${BASE}/api/v1/data-exports/${ex.body.id}/download`, {
          headers: { Authorization: `Bearer ${token}` },
        })
      : null;
    if (ex.status === 429)
      note(
        "22 export everything: limited after a recent export (correct)",
        true,
      );
    else
      note(
        "22 export everything: zip ready and downloads",
        ready && dl?.status() === 200,
        `start ${ex.status}, ready ${ready}, download ${dl?.status()}`,
      );
    const other = await api(ctx, token, "POST", "/leads", {
      first_name: "Erase",
      last_name: "Me",
      identities: [{ type: "phone", value: PHONE(9) }],
      source_id: source.id,
    });
    const er = await api(ctx, token, "POST", `/leads/${other.body?.id}/erase`, {
      confirm: "ERASE",
    });
    note("22 erase a person", er.status < 300, `status ${er.status}`);
  });

  await test.step("23-languages", async () => {
    const page = await (await browser.newContext()).newPage();
    await signIn(page);
    await page.goto(`${BASE}/account`);
    await page.getByRole("combobox", { name: "Language" }).selectOption("ar");
    const rtl = await page.locator("html").getAttribute("dir");
    const title = await page.getByRole("heading", { name: "حسابي" }).count();
    await page.getByRole("combobox", { name: "اللغة" }).selectOption("hi");
    const hindi = await page.getByRole("heading", { name: "मेरा खाता" }).count();
    await page.getByRole("combobox", { name: "भाषा" }).selectOption("");
    note(
      "23 Arabic (right to left) and Hindi",
      rtl === "rtl" && title > 0 && hindi > 0,
      `dir ${rtl}, arabic title ${title}, hindi title ${hindi}`,
    );
  });

  console.log(
    "\nWALKTHROUGH RESULTS\n" +
      Object.entries(results)
        .map(([k, v]) => `${v.startsWith("PASS") ? "✅" : "❌"} ${k}: ${v}`)
        .join("\n"),
  );
});
