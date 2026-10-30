"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
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

/**
 * The console's data layer (TanStack Query against the API proxy), toasts, and Motion with its
 * DOM features only. Motion follows the reduced-motion setting: transforms are skipped for people
 * who asked for less motion.
 */
export function DataProviders({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      <MotionConfig reducedMotion="user">
        <LazyMotion features={domAnimation} strict>
          {children}
        </LazyMotion>
      </MotionConfig>
      <Toaster />
    </QueryClientProvider>
  );
}
