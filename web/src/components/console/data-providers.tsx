"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import { useState, type ReactNode } from "react";

import { Toaster } from "@/components/ui/sonner";
import { ApiError } from "@/lib/api/client";

function makeQueryClient(): QueryClient {
  // A server that stopped answering: check its health now, so the sidebar says so at once
  // and says it is back as soon as it is, rather than at the next half-minute check.
  const unanswered = (error: unknown) => {
    if (error instanceof ApiError && error.unreachable) {
      void client.invalidateQueries({ queryKey: ["health"] });
    }
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // A rejected key (rotated, expired cookie): re-check the session so the console asks to
      // sign in again instead of showing errors everywhere.
      onError: (error, query) => {
        if (error instanceof ApiError && error.needsSignIn && query.queryKey[0] !== "session") {
          void client.invalidateQueries({ queryKey: ["session"] });
        }
        if (query.queryKey[0] !== "health") unanswered(error);
      },
    }),
    mutationCache: new MutationCache({ onError: unanswered }),
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: true,
        // A busy server (429) is asked again, a little later each time; other refusals are not.
        retry: (failures, error) =>
          error instanceof ApiError && error.status === 429
            ? failures < 4
            : !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
              failures < 2,
        retryDelay: (failures, error) =>
          error instanceof ApiError && error.status === 429
            ? Math.min(2_000 * 2 ** failures, 15_000)
            : Math.min(1_000 * 2 ** failures, 30_000),
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
