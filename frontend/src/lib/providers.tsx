"use client";

import {
  dehydrate,
  hydrate,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { setUnauthorizedHandler } from "./api-client";

export const COMPENSATION_CACHE_STORAGE_KEY = "koc-compensation-query-cache-v1";

function restoreCompensationCache(queryClient: QueryClient) {
  if (typeof window === "undefined") return;
  try {
    const serialized = window.sessionStorage.getItem(COMPENSATION_CACHE_STORAGE_KEY);
    if (serialized) hydrate(queryClient, JSON.parse(serialized));
  } catch {
    window.sessionStorage.removeItem(COMPENSATION_CACHE_STORAGE_KEY);
  }
}

function persistCompensationCache(queryClient: QueryClient) {
  if (typeof window === "undefined") return;
  try {
    const state = dehydrate(queryClient, {
      shouldDehydrateQuery: (query) =>
        query.queryKey[0] === "compensation" && query.state.status === "success",
    });
    window.sessionStorage.setItem(
      COMPENSATION_CACHE_STORAGE_KEY,
      JSON.stringify(state),
    );
  } catch {
    // A full sessionStorage quota must never break the dashboard.
    window.sessionStorage.removeItem(COMPENSATION_CACHE_STORAGE_KEY);
  }
}

export function clearPersistedQueryCache() {
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(COMPENSATION_CACHE_STORAGE_KEY);
  }
}

export function AppProviders({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [client] = useState(() => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
          staleTime: 60_000,
          gcTime: 30 * 60_000,
          refetchOnWindowFocus: false,
          refetchOnReconnect: false,
        },
      },
    });
    restoreCompensationCache(queryClient);
    return queryClient;
  });

  useEffect(() => {
    let timer: number | undefined;
    const unsubscribe = client.getQueryCache().subscribe(() => {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = window.setTimeout(() => persistCompensationCache(client), 250);
    });
    persistCompensationCache(client);
    return () => {
      unsubscribe();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [client]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        router.replace("/login");
      }
    });
  }, [router]);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
