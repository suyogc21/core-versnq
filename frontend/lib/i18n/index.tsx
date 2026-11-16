"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { ar } from "./ar";
import { hi } from "./hi";

/**
 * Core's screens in more languages (finishing plan, batch 6): English, Arabic (right to left)
 * and Hindi. Texts are looked up by their English wording, so a screen not translated yet
 * simply stays in English. Each person picks a language for their device (My account);
 * otherwise the company's language (Settings → Company) is used.
 */
export const LANGUAGES = [
  { code: "en", name: "English", dir: "ltr" },
  { code: "ar", name: "العربية", dir: "rtl" },
  { code: "hi", name: "हिन्दी", dir: "ltr" },
] as const;
export type Lang = (typeof LANGUAGES)[number]["code"];

const DICTS: Record<Lang, Record<string, string>> = { en: {}, ar, hi };
const KEY = "versnq.lang";

function known(code: string | null | undefined): Lang | null {
  const short = (code ?? "").slice(0, 2);
  return LANGUAGES.some((l) => l.code === short) ? (short as Lang) : null;
}

/** This device's choice, if any (kept in the browser; not shared). */
export function deviceLang(): Lang | null {
  try {
    return known(window.localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

export function setDeviceLang(code: Lang | null) {
  try {
    if (code) window.localStorage.setItem(KEY, code);
    else window.localStorage.removeItem(KEY);
  } catch {
    /* private window: the company's language is used */
  }
}

type Ctx = { lang: Lang; dir: "ltr" | "rtl"; t: (text: string, vars?: Record<string, string | number>) => string; setLang: (l: Lang | null) => void };

function translate(lang: Lang, text: string, vars?: Record<string, string | number>) {
  let out = DICTS[lang][text] ?? text;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, String(v));
  return out;
}

const I18n = createContext<Ctx>({ lang: "en", dir: "ltr", t: (s, v) => translate("en", s, v), setLang: () => {} });

/** Wraps the signed-in app; `companyLang` is the company's language from its settings. */
export function LanguageProvider({ companyLang, children }: { companyLang?: string | null; children: React.ReactNode }) {
  const [device, setDevice] = useState<Lang | null>(() => (typeof window === "undefined" ? null : deviceLang()));
  const lang: Lang = device ?? known(companyLang) ?? "en";
  const dir = LANGUAGES.find((l) => l.code === lang)!.dir;
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }, [lang, dir]);
  const value = useMemo<Ctx>(
    () => ({
      lang,
      dir,
      t: (s, v) => translate(lang, s, v),
      setLang: (l) => {
        setDeviceLang(l);
        setDevice(l);
      },
    }),
    [lang, dir],
  );
  return <I18n.Provider value={value}>{children}</I18n.Provider>;
}

export function useT() {
  return useContext(I18n);
}
