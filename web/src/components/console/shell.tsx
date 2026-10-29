"use client";

import {
  BookOpenIcon,
  FlaskConicalIcon,
  GaugeIcon,
  InboxIcon,
  LibraryIcon,
  LogOutIcon,
  MenuIcon,
  MessageSquareTextIcon,
  PlusIcon,
  SettingsIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { Wordmark } from "@/components/aria/wordmark";
import { SignIn } from "@/components/console/sign-in";
import { ErrorState } from "@/components/console/states";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Dialog, DialogTitle, DialogTrigger, SheetContent } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useHealth, useRuns, useSession, useSignOut } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
}

const NAV: { label: string; items: NavItem[] }[] = [
  {
    label: "Triage",
    items: [
      { href: "/console", label: "Overview", icon: GaugeIcon, exact: true },
      { href: "/console/runs", label: "Incidents", icon: InboxIcon },
      { href: "/console/runs/new", label: "New triage", icon: PlusIcon, exact: true },
      { href: "/console/ask", label: "Ask ARIA", icon: MessageSquareTextIcon },
    ],
  },
  {
    label: "Knowledge",
    items: [
      { href: "/console/memory", label: "Incident memory", icon: LibraryIcon },
      { href: "/console/runbooks", label: "Runbooks", icon: BookOpenIcon },
      { href: "/console/evals", label: "Evaluation", icon: FlaskConicalIcon },
    ],
  },
  {
    label: "System",
    items: [{ href: "/console/settings", label: "Settings", icon: SettingsIcon }],
  },
];

function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.href;
  if (item.href === "/console/runs") {
    return pathname.startsWith("/console/runs") && pathname !== "/console/runs/new";
  }
  return pathname.startsWith(item.href);
}

function ReviewCount() {
  const { data } = useRuns("awaiting_review", 50);
  const n = data?.runs.length ?? 0;
  if (n === 0) return null;
  return (
    <span className="tabular ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-[0.6875rem] font-medium text-primary-foreground">
      <span className="sr-only">, </span>
      {n >= 50 ? "50+" : n}
      <span className="sr-only"> waiting for review</span>
    </span>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Console" className="grid gap-6">
      {NAV.map((group) => (
        <div key={group.label} role="group" aria-labelledby={`nav-${group.label}`}>
          <p id={`nav-${group.label}`} className="eyebrow mb-2 px-3 text-faint">
            {group.label}
          </p>
          <div className="grid gap-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href as never}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors duration-(--duration-quick)",
                    active
                      ? "bg-raised font-medium text-heading"
                      : "text-muted-foreground hover:bg-raised/60 hover:text-heading",
                  )}
                >
                  <Icon
                    aria-hidden
                    strokeWidth={1.75}
                    className={cn("size-4", active ? "text-primary" : "text-faint")}
                  />
                  {item.label}
                  {item.href === "/console/runs" ? <ReviewCount /> : null}
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function ApiStatus() {
  const { data, isError } = useHealth();
  const state = isError ? "down" : !data ? "unknown" : data.status === "ok" ? "ok" : "degraded";
  const label = {
    ok: "API ready",
    degraded: data?.llm === false ? "API ready, no LLM (deterministic mode)" : "API degraded",
    down: "API not reachable",
    unknown: "Checking the API",
  }[state];
  return (
    <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
      <span
        aria-hidden
        className={cn(
          "block size-2 shrink-0 rounded-full",
          state === "ok" && "bg-ok",
          state === "degraded" && "bg-sev3",
          state === "down" && "bg-danger",
          state === "unknown" && "bg-control",
        )}
      />
      <span>
        {label}
        {data ? <span className="text-faint"> (v{data.version})</span> : null}
      </span>
    </p>
  );
}

function SessionFooter() {
  const { data: session } = useSession();
  const signOut = useSignOut();
  return (
    <div className="grid gap-3 border-t border-rule pt-4">
      <ApiStatus />
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-xs text-muted-foreground">
          {session?.signedIn ? (
            <>
              Signed in as <span className="font-medium text-foreground">{session.name}</span>
            </>
          ) : session?.authRequired === false ? (
            "Open API: no key needed"
          ) : null}
        </p>
        <div className="flex items-center">
          <ThemeToggle />
          {session?.signedIn ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Sign out"
              onClick={() => signOut.mutate()}
            >
              <LogOutIcon aria-hidden />
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Gate({ children }: { children: ReactNode }) {
  const session = useSession();
  if (session.isPending) {
    return (
      <div role="status" className="grid gap-4">
        <span className="sr-only">Connecting to ARIA</span>
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (session.isError || !session.data?.reachable) {
    return (
      <ErrorState
        title="The console cannot reach the ARIA API"
        error={
          new Error(
            "Start the API (make dev, or docker compose up) and check that this web server's ARIA_API_URL points at it.",
          )
        }
        onRetry={() => void session.refetch()}
      />
    );
  }
  if (session.data.authRequired && !session.data.signedIn) return <SignIn />;
  return <>{children}</>;
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider delayDuration={300}>
      <a
        href="#console-main"
        className="sr-only z-50 rounded-sm bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
        <aside className="hidden bg-sunken lg:block">
          <div className="sticky top-0 flex h-dvh flex-col gap-8 px-4 py-6">
            <Link href="/" className="rounded-sm px-3 text-heading" aria-label="ARIA home">
              <Wordmark />
            </Link>
            <div className="flex-1 overflow-y-auto">
              <Nav />
            </div>
            <SessionFooter />
          </div>
        </aside>
        <div className="flex min-w-0 flex-col">
          <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-rule bg-background/95 px-4 py-3 backdrop-blur lg:hidden">
            <Dialog open={open} onOpenChange={setOpen}>
              <DialogTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Open navigation">
                  <MenuIcon aria-hidden />
                </Button>
              </DialogTrigger>
              <SheetContent side="left" closeLabel="Close navigation">
                <DialogTitle className="sr-only">Navigation</DialogTitle>
                <Link href="/" className="rounded-sm px-1.5" onClick={() => setOpen(false)}>
                  <Wordmark />
                </Link>
                <div className="flex-1 overflow-y-auto">
                  <Nav onNavigate={() => setOpen(false)} />
                </div>
                <SessionFooter />
              </SheetContent>
            </Dialog>
            <Link href="/console" className="rounded-sm text-heading" aria-label="Console overview">
              <Wordmark />
            </Link>
            <ThemeToggle />
          </header>
          <main
            id="console-main"
            className="mx-auto w-full max-w-[90rem] flex-1 px-4 py-6 sm:px-6 lg:px-10 lg:py-10"
          >
            <Gate>{children}</Gate>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
