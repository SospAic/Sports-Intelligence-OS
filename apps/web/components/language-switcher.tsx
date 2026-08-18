"use client";

import { Check, ChevronDown, Languages } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  isUiLanguageCode,
  UI_LANGUAGE_OPTIONS,
} from "@/lib/language-options";
import { languageOptionLabel, useUiLanguage } from "@/lib/ui-i18n";

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useUiLanguage();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const current = UI_LANGUAGE_OPTIONS.find((item) => item.value === locale) ?? UI_LANGUAGE_OPTIONS[0];

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const changeLocale = (value: string) => {
    if (!isUiLanguageCode(value)) return;
    setLocale(value);
    setOpen(false);
  };

  return (
    <div className="relative shrink-0" ref={containerRef}>
      <button
        type="button"
        aria-label={t("shell.language")}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={t("shell.language")}
        className="flex h-9 items-center gap-1.5 rounded-lg border border-slate-700 px-2 text-xs text-slate-300 transition hover:border-cyan-700 hover:bg-slate-900 hover:text-white"
        onClick={() => setOpen((value) => !value)}
      >
        <Languages size={16} className="text-cyan-300" />
        <span className="hidden lg:inline">{languageOptionLabel(locale)}</span>
        <ChevronDown size={13} className="text-slate-500" />
      </button>
      {open && (
        <div
          className="absolute top-11 right-0 z-50 w-64 rounded-xl border border-slate-700 bg-slate-950 p-2 shadow-2xl"
          role="listbox"
          aria-label={t("shell.language")}
        >
          <div className="border-b border-slate-800 px-3 py-2">
            <p className="text-sm font-medium text-white">{t("shell.language")}</p>
            <p className="mt-1 text-[11px] leading-4 text-slate-500">
              {t("shell.languageSavedLocally")}
            </p>
          </div>
          <div className="mt-1 space-y-0.5">
            {UI_LANGUAGE_OPTIONS.map((item) => (
              <button
                key={item.value}
                type="button"
                role="option"
                aria-selected={item.value === locale}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-slate-900"
                onClick={() => changeLocale(item.value)}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-slate-200">{item.label}</span>
                  {item.nativeLabel !== item.label && (
                    <span className="mt-0.5 block text-[11px] text-slate-500">
                      {item.nativeLabel}
                    </span>
                  )}
                </span>
                  {item.value === locale && <Check size={16} className="text-cyan-300" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
