"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState, type ReactNode } from "react";

import { Toaster } from "@/components/ui/sonner";
import { ApiError } from "@/lib/api/client";

function makeQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // A rejected key (rotated, expired cookie): re-check the session so the console asks to
      // sign in again instead of showing errors everywhere.
      onError: (error, query) => {
        if (error instanceof ApiError && error.needsSignIn && query.queryKey[0] !== "session") {
          void client.invalidateQueries({ queryKey: ["session"] });
        }
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: true,
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
      },
    },
  });
  return client;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        {children}
        <Toaster />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
