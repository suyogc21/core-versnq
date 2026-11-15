import { expect, test } from "@playwright/test";

import { companyWithTeams } from "./api";
import { signIn } from "./helpers";

/**
 * Step O2 (Decision log #44): a manager builds a campaign in the browser: imports a CSV (an
 * existing lead is skipped: "Already your lead? Never a cold email."), writes the email, launches;
 * the worker sends it from the sending inbox; the person replies; the reply is in Outreach →
 * Replies, and Convert to lead opens the new lead.
 */
test("a campaign goes from CSV to a reply to a lead", async ({ browser }) => {
  test.setTimeout(180_000);
  const { base, manager, call, ownerToken } = await companyWithTeams("litware", ["outreach"]);
  await call("POST", "/api/v1/sending-inboxes", {
    email_address: "sales@litware.example.org",
    password: "app-pass-1",
    imap_host: "imap.mail.example",
    smtp_host: "smtp.mail.example",
    min_gap_minutes: 0,
  });
  const sources = await call("GET", "/api/v1/lead-sources");
  await call("POST", "/api/v1/leads", {
    first_name: "Kiran",
    source_id: sources[0].id,
    identities: [{ type: "email", value: "kiran@known.example" }],
  });

  const page = await (await browser.newContext()).newPage();
  await signIn(page, base, manager.email, manager.password);
  await page.getByRole("complementary").getByRole("link", { name: "Outreach", exact: true }).click();
  await page.getByRole("button", { name: "New campaign" }).click();
  await page.getByLabel("Campaign name").fill("Founders in Pune");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page).toHaveURL(/\/outreach\/[0-9a-f-]+$/);
  const campaignId = page.url().split("/").pop() as string;

  // Contacts: the existing lead is skipped, the bad row too.
  const csv = "Email,First name,Company,City\nasha@prospect.example,Asha,Acme,Pune\nkiran@known.example,Kiran,Known,Pune\nnot-an-email,X,Y,Z\n";
  await page.getByLabel("CSV file").setInputFiles({ name: "people.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Check the file" }).click();
  const report = page.getByTestId("import-report");
  await expect(report.getByText("1 will be added")).toBeVisible();
  await expect(report.getByText("1 already a lead or customer (skipped)")).toBeVisible();
  await page.getByRole("button", { name: "Add 1 contacts" }).click();
  await expect(page.locator('[data-contact="asha@prospect.example"]')).toBeVisible();

  // The email.
  await page.getByRole("tab", { name: "Sequence" }).click();
  await page.getByLabel("Step 1 version A subject").fill("A quick idea for {{company}}");
  await page.getByLabel("Step 1 version A body").fill("Hi {{first_name|there}}, worth a chat about {{city}}?");
  await page.getByRole("button", { name: "Save sequence" }).click();
  await expect(page.getByText("Sequence saved")).toBeVisible();
  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByTestId("preview").getByText("A quick idea for Acme")).toBeVisible();

  // Any hour, so the test does not depend on the clock; then launch.
  await call("PATCH", `/api/v1/campaigns/${campaignId}`, { schedule: { days: [0, 1, 2, 3, 4, 5, 6], from: "00:00", to: "24:00" } });
  await page.getByRole("button", { name: "Launch" }).click();
  await expect(page.getByText("Launched.")).toBeVisible();

  // The worker sends it (every 30 seconds).
  await expect.poll(async () => (await call("GET", `/api/v1/campaigns/${campaignId}`)).counts.sent, { timeout: 90_000 }).toBe(1);

  // Asha replies.
  const res = await page.request.post(`${base}/api/v1/inbox/test-inbound`, {
    headers: { Authorization: `Bearer ${ownerToken}`, "Content-Type": "message/rfc822" },
    data: "From: Asha <asha@prospect.example>\r\nTo: sales@litware.example.org\r\nSubject: Re: A quick idea for Acme\r\nMessage-ID: <r1@prospect.example>\r\n\r\nYes, let's talk on Tuesday.\r\n",
  });
  expect((await res.json()).stored).toBe(true);

  await page.getByRole("complementary").getByRole("link", { name: "Outreach", exact: true }).click();
  await page.getByRole("tab", { name: "Replies" }).click();
  await page.locator('[data-reply="asha@prospect.example"]').click();
  const thread = page.locator('[data-thread="asha@prospect.example"]');
  await expect(thread.getByText("Yes, let's talk on Tuesday.")).toBeVisible();
  await expect(thread.getByText("Hi Asha, worth a chat about Pune?")).toBeVisible();

  // Step O3: a person sorts the reply; a draft arrives (as ACE would send it); approve and send.
  await thread.getByRole("button", { name: "Not sorted" }).click();
  await thread.getByLabel("Category").selectOption({ label: "Question" });
  await expect(page.getByText("Sorted. Done: draft")).toBeVisible();
  const [conv] = await call("GET", "/api/v1/outreach/conversations");
  const detail = await call("GET", `/api/v1/outreach/conversations/${conv.id}`);
  const theirs = detail.messages.find((m: { direction: string }) => m.direction === "in");
  await call("POST", `/api/v1/conversations/${conv.id}/drafts`, { reply_to_message_id: theirs.id, body: "Tuesday at 11 works. Talk then!", reasons: [] });
  await page.reload();
  await page.getByRole("tab", { name: "Replies" }).click();
  await page.locator('[data-reply="asha@prospect.example"]').click();
  const draft = page.getByTestId("draft");
  await expect(draft.getByText("Tuesday at 11 works. Talk then!")).toBeVisible();
  await draft.getByRole("button", { name: "Approve and send" }).click();
  await expect(page.getByText("Sent", { exact: true })).toBeVisible();
  await expect(thread.getByText("Tuesday at 11 works. Talk then!")).toBeVisible();

  await thread.getByRole("button", { name: "Convert to lead" }).click();
  await expect(page).toHaveURL(/\/leads\/[0-9a-f-]+$/);
  await expect(page.getByText("Asha").first()).toBeVisible();
});

