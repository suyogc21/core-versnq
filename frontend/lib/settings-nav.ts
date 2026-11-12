import { Activity, Boxes, Building2, Code, Inbox, Mail, MessageCircle, ReceiptText, Shield, Users, UsersRound, Workflow } from "lucide-react";

/** Every settings page, its group and who may open it. The sidebar shows one "Settings"
 * entry when any of these is allowed; typing an address you may not use is refused. */
export type SettingsPage = {
  href: string;
  title: string;
  hint: string;
  group: "Company" | "People" | "Your records" | "Money" | "Getting leads in" | "Automation" | "Developers" | "Security";
  permission: string;
  icon: typeof Users;
};

export const SETTINGS_PAGES: SettingsPage[] = [
  { href: "/settings/company", title: "Company", hint: "Name for your records, region, time zone and branding", group: "Company", permission: "settings.manage", icon: Building2 },
  { href: "/settings/users", title: "Users", hint: "Invite people, change roles, disable access", group: "People", permission: "users.read", icon: Users },
  { href: "/settings/teams", title: "Teams", hint: "Teams and their managers", group: "People", permission: "users.read", icon: UsersRound },
  { href: "/settings/roles", title: "Roles", hint: "What each role may do and see, including every record type", group: "People", permission: "roles.manage", icon: Shield },
  { href: "/settings/records", title: "Records and fields", hint: "Fields, stages and rules for each kind of record, and how they link", group: "Your records", permission: "crm.configure", icon: Boxes },
  { href: "/settings/money", title: "Money", hint: "Billing entities, taxes, Razorpay / Stripe, the mailbox invoices go from, reminders", group: "Money", permission: "money.settings", icon: ReceiptText },
  { href: "/settings/lead-capture", title: "Lead capture", hint: "Web forms, who gets new leads, response times, duplicates", group: "Getting leads in", permission: "crm.configure", icon: Inbox },
  { href: "/settings/inboxes", title: "Connected inboxes", hint: "Connected mailboxes and WhatsApp extensions, copy-in address, addresses never synced", group: "People", permission: "mailboxes.manage", icon: Mail },
  { href: "/settings/whatsapp", title: "WhatsApp", hint: "The company's official number, its templates, automatic replies and STOP words", group: "Getting leads in", permission: "whatsapp.manage", icon: MessageCircle },
  { href: "/settings/automations", title: "Automations", hint: "When something happens, do something: tasks, tags, owners, stages, alerts, webhooks", group: "Automation", permission: "crm.configure", icon: Workflow },
  { href: "/settings/developers", title: "Developers", hint: "API keys, webhooks, and the log of every call and message", group: "Developers", permission: "integrations.manage", icon: Code },
  { href: "/settings/audit", title: "Audit log", hint: "Who changed what, and when", group: "Security", permission: "audit.read", icon: Activity },
];

/** The settings page an address belongs to (for permission checks), if any. */
export function settingsPageFor(path: string): SettingsPage | undefined {
  return SETTINGS_PAGES.find((p) => path === p.href || path.startsWith(`${p.href}/`));
}
