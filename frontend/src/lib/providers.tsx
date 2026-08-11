"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { setUnauthorizedHandler } from "./api-client";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            staleTime: 60_000,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        router.replace("/login");
      }
    });
  }, [router]);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
