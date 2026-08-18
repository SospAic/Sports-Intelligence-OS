"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ToastProvider } from "@/components/toast";
import { UiLanguageProvider } from "@/lib/ui-i18n";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, retry: 1 },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <UiLanguageProvider>
        <ToastProvider>
          <AppShell>{children}</AppShell>
        </ToastProvider>
      </UiLanguageProvider>
    </QueryClientProvider>
  );
}
