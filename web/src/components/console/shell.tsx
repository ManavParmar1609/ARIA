"use client";

import {
  BookOpenIcon,
  CompassIcon,
  FlaskConicalIcon,
  GaugeIcon,
  InboxIcon,
  LibraryIcon,
  LogOutIcon,
  MenuIcon,
  MessageSquareTextIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { Wordmark } from "@/components/aria/wordmark";
import { ConsoleCommands, useCommands } from "@/components/console/command-palette";
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
      { href: "/console/guide", label: "How to use ARIA", icon: CompassIcon },
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

const noop = () => () => {};

/** Whether to show the Mac key (⌘) or Ctrl in hints; Ctrl until the browser says otherwise. */
function useIsMac(): boolean {
  return useSyncExternalStore(
    noop,
    () => /Mac|iPhone|iPad/.test(navigator.platform),
    () => false,
  );
}

/** Opens the command palette; the hint shows the shortcut for this computer. */
function PaletteButton() {
  const { openPalette } = useCommands();
  const mac = useIsMac();
  return (
    <button
      type="button"
      onClick={openPalette}
      aria-keyshortcuts="Control+K Meta+K"
      className="flex h-10 w-full items-center gap-2.5 rounded-md bg-foreground/6 px-3 text-[0.9375rem] text-muted-foreground transition-colors duration-(--duration-quick) hover:bg-foreground/10 hover:text-foreground"
    >
      <SearchIcon aria-hidden className="size-4" />
      <span className="flex-1 text-left">Search</span>
      <kbd className="rounded-xs border border-control/60 px-1.5 text-xs">
        {mac ? "⌘ K" : "Ctrl K"}
      </kbd>
    </button>
  );
}

function PaletteIconButton() {
  const { openPalette } = useCommands();
  return (
    <Button variant="ghost" size="icon-sm" aria-label="Search or jump to" onClick={openPalette}>
      <SearchIcon aria-hidden />
    </Button>
  );
}

function ReviewCount() {
  const { data } = useRuns("awaiting_review", 50);
  const n = data?.runs.length ?? 0;
  if (n === 0) return null;
  return (
    <span className="tabular ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-foreground px-1.5 text-xs font-medium text-background">
      <span className="sr-only">, </span>
      {n >= 50 ? "50+" : n}
      <span className="sr-only"> waiting for review</span>
    </span>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const nav = useRef<HTMLElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const lastY = useRef<number | null>(null);

  // A grass pill glides from the page you left to the one you opened (a vertical translate:
  // every item is the same size). Until it has measured, the current link keeps its own grass
  // background, so the first paint and no-script views are unchanged.
  useLayoutEffect(() => {
    const el = pill.current;
    const root = nav.current;
    if (!el || !root) return;
    const link = root.querySelector<HTMLElement>('a[aria-current="page"]');
    if (!link) {
      el.style.opacity = "0";
      lastY.current = null;
      return;
    }
    const y = link.offsetTop;
    el.style.left = `${link.offsetLeft}px`;
    el.style.width = `${link.offsetWidth}px`;
    el.style.height = `${link.offsetHeight}px`;
    el.style.transition = "none";
    el.style.transform = `translateY(${lastY.current ?? y}px)`;
    void el.offsetWidth;
    el.style.transition = "";
    el.style.transform = `translateY(${y}px)`;
    el.style.opacity = "1";
    lastY.current = y;
    root.dataset.pill = "on";
  }, [pathname]);

  return (
    <nav ref={nav} aria-label="Console" className="group/nav relative grid gap-4">
      <span
        ref={pill}
        aria-hidden
        className="absolute top-0 left-0 rounded-md bg-grass opacity-0 transition-[transform,opacity] duration-(--duration-slow) ease-(--ease-out)"
      />
      {NAV.map((group) => (
        <div key={group.label} role="group" aria-labelledby={`nav-${group.label}`}>
          <p id={`nav-${group.label}`} className="eyebrow mb-1.5 px-3 text-muted-foreground">
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
                    "relative flex h-9 items-center gap-3 rounded-md px-3 text-[0.9375rem] transition-colors duration-(--duration-quick)",
                    active
                      ? "bg-grass font-medium text-pop-ink group-data-[pill=on]/nav:bg-transparent"
                      : "text-foreground hover:bg-foreground/6",
                  )}
                >
                  <Icon
                    aria-hidden
                    strokeWidth={1.75}
                    className={cn("size-4", active ? "text-pop-ink" : "text-muted-foreground")}
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
  // "degraded" with the database up means no LLM is configured: offline mode, which works.
  const offline = data?.status === "degraded" && data.llm === false && data.database;
  const state = isError
    ? "down"
    : !data
      ? "unknown"
      : data.status === "ok" || offline
        ? "ok"
        : "degraded";
  const label = {
    ok: offline ? "API ready, offline mode" : "API ready",
    degraded: "API degraded",
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
            "No key needed: this API is open"
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

// Pages that need no live API: the evaluation reads the committed results, and the guide is
// mostly words. They stay readable while the API is down, and before anyone signs in.
const WITHOUT_API = new Set(["/console/evals", "/console/guide"]);

/** Once the page's content is in, scroll to the link's #section: it was not there on load. */
function useHashOnArrival(ready: boolean) {
  const done = useRef(false);
  useEffect(() => {
    if (!ready || done.current) return;
    done.current = true;
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) document.getElementById(id)?.scrollIntoView();
  }, [ready]);
}

function Gate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const session = useSession();
  const open = WITHOUT_API.has(pathname);
  const reachable = !session.isError && Boolean(session.data?.reachable);
  const signedOut = Boolean(session.data?.authRequired && !session.data.signedIn);
  useHashOnArrival(open || (reachable && !signedOut));
  if (open) return <>{children}</>;
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
      <div className="grid gap-4">
        <ErrorState
          title="ARIA's API is not answering"
          error={
            new Error(
              "Runs, reviews and incident memory need it. If you run ARIA yourself, start it with make dev or docker compose up, and check that this web server's ARIA_API_URL points at it.",
            )
          }
          onRetry={() => void session.refetch()}
        />
        <p className="text-sm text-muted-foreground">
          These work without it:{" "}
          <Link href="/console/evals" className="underline decoration-control underline-offset-4">
            the evaluation
          </Link>{" "}
          and{" "}
          <Link href="/console/guide" className="underline decoration-control underline-offset-4">
            how to use ARIA
          </Link>
          .
        </p>
      </div>
    );
  }
  if (session.data.authRequired && !session.data.signedIn) return <SignIn />;
  return <>{children}</>;
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <TooltipProvider delayDuration={300}>
      <ConsoleCommands>
        <a
          href="#console-main"
          className="sr-only z-50 rounded-sm bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <div className="min-h-dvh lg:grid lg:grid-cols-[17.5rem_minmax(0,1fr)]">
          {/* A floating white panel on the cream page, like the site's navigation bars. */}
          <aside className="hidden p-3 lg:block">
            <div className="sticky top-3 flex h-[calc(100dvh-1.5rem)] flex-col gap-4 rounded-lg bg-raised px-3 py-4">
              <Link href="/" className="rounded-sm px-3" aria-label="ARIA home">
                <Wordmark />
              </Link>
              <PaletteButton />
              {/* the padding keeps the links' focus rings inside the scrolling box */}
              <div className="-mx-1 flex-1 overflow-y-auto px-1 py-1">
                <Nav />
              </div>
              <SessionFooter />
            </div>
          </aside>
          <div className="flex min-w-0 flex-col">
            <header className="sticky top-0 z-30 bg-background px-3 pt-3 lg:hidden">
              <div className="flex h-14 items-center justify-between gap-3 rounded-md bg-raised px-2">
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
                <Link href="/console" className="rounded-sm" aria-label="ARIA console overview">
                  <Wordmark />
                </Link>
                <div className="flex items-center">
                  <PaletteIconButton />
                  <ThemeToggle />
                </div>
              </div>
            </header>
            <main
              id="console-main"
              className="mx-auto w-full max-w-[90rem] flex-1 px-4 py-8 sm:px-6 lg:px-8 lg:py-12"
            >
              <Gate>{children}</Gate>
            </main>
          </div>
        </div>
      </ConsoleCommands>
    </TooltipProvider>
  );
}
