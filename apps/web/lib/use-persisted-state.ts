"use client";
import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";

/**
 * State that persists to URL search params (for filters/shareable state)
 */
export function useUrlState(key: string, defaultValue: string): [string, (v: string) => void] {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const value = searchParams.get(key) ?? defaultValue;

  const setValue = useCallback((newValue: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (newValue === defaultValue) {
      params.delete(key);
    } else {
      params.set(key, newValue);
    }
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [key, defaultValue, searchParams, router, pathname]);

  return [value, setValue];
}

/**
 * State that persists to localStorage (for personal preferences)
 */
export function useLocalStorageState<T>(key: string, defaultValue: T): [T, (v: T | ((prev: T) => T)) => void] {
  const storageKey = `sio:${key}`;
  const [state, setState] = useState<T>(() => {
    if (typeof window === "undefined") return defaultValue;
    try {
      const stored = localStorage.getItem(storageKey);
      return stored ? JSON.parse(stored) : defaultValue;
    } catch {
      return defaultValue;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(state));
    } catch { /* ignore quota errors */ }
  }, [storageKey, state]);

  return [state, setState];
}
