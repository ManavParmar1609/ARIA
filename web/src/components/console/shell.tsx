"use client";

import {
  BookOpenIcon,
  CompassIcon,
  FlaskConicalIcon,
  InboxIcon,
  LibraryIcon,
  LogOutIcon,
  MenuIcon,
  MessageSquareTextIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  SparklesIcon,
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
import {
  useHealth,
  useModelKey,
  useRuns,
  useSession,
  useSettingsView,
  useSignOut,
} from "@/lib/api/hooks";
import { accessShort, modelAccess } from "@/lib/model-access";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
}

// Three groups with a rule between them: the main tasks, the library, and about ARIA. Each group
// is named for screen readers only, so the menu reads as one short list.
const NAV: { label: string; items: NavItem[] }[] = [
  {
    label: "Triage",
    items: [
      { href: "/console/runs/new", label: "New triage", icon: PlusIcon, exact: true },
      { href: "/console/runs", label: "Incidents", icon: InboxIcon },
      { href: "/console/ask", label: "Ask ARIA", icon: MessageSquareTextIcon },
    ],
  },
  {
    label: "Library",
    items: [
      { href: "/console/memory", label: "Incident library", icon: LibraryIcon },
      { href: "/console/runbooks", label: "Runbooks", icon: BookOpenIcon },
    ],
  },
  {
    label: "About ARIA",
    items: [
      { href: "/console/how-it-works", label: "How ARIA works", icon: SparklesIcon },
      { href: "/console/evals", label: "Test results", icon: FlaskConicalIcon },
      { href: "/console/guide", label: "Guide", icon: CompassIcon },
      { href: "/console/settings", label: "Settings", icon: SettingsIcon },
    ],
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
      className="flex h-10 w-full items-center gap-2.5 rounded-md bg-foreground/6 px-3 text-sm text-muted-foreground transition-colors duration-(--duration-quick) hover:bg-foreground/10 hover:text-foreground"
    >
      <SearchIcon aria-hidden className="size-4" />
      <span className="flex-1 text-left">Search</span>
      <kbd className="rounded-md border border-control/50 px-1.5 text-xs [@media(pointer:coarse)]:hidden">
        {mac ? "⌘ K" : "Ctrl K"}
      </kbd>
    </button>
  );
}

function PaletteIconButton() {
  const { openPalette } = useCommands();
  return (
    <Button variant="ghost" size="icon-sm" aria-label="Search" onClick={openPalette}>
      <SearchIcon aria-hidden />
    </Button>
  );
}

function ReviewCount() {
  const { data } = useRuns("awaiting_review", 50, 30_000);
  // A shared demo's examples wait too, but nobody reviews them: only one's own incidents count.
  const n = data?.runs.filter((run) => !run.example).length ?? 0;
  if (n === 0) return null;
  return (
    <span className="tabular ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-medium text-primary-foreground">
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

  // A grass pill glides from the page you left to the one you opened (a vertical translate:
  // every item is the same size), starting from where it is drawn now, so a quick second click
  // turns it around rather than making it jump. Until it has measured, the current link keeps its
  // own grass background, so the first paint and no-script views are unchanged.
  useLayoutEffect(() => {
    const el = pill.current;
    const root = nav.current;
    if (!el || !root) return;
    const link = root.querySelector<HTMLElement>('a[aria-current="page"]');
    if (!link) {
      el.style.opacity = "0";
      return;
    }
    const y = link.offsetTop;
    const from =
      el.style.opacity === "1"
        ? el.getBoundingClientRect().top - root.getBoundingClientRect().top
        : y;
    el.style.left = `${link.offsetLeft}px`;
    el.style.width = `${link.offsetWidth}px`;
    el.style.height = `${link.offsetHeight}px`;
    el.style.transition = "none";
    el.style.transform = `translateY(${from}px)`;
    void el.offsetWidth;
    el.style.transition = "";
    el.style.transform = `translateY(${y}px)`;
    el.style.opacity = "1";
    root.dataset.pill = "on";
  }, [pathname]);

  return (
    <nav ref={nav} aria-label="Console" className="group/nav relative grid gap-4">
      <span
        ref={pill}
        aria-hidden
        className="absolute top-0 left-0 rounded-sm bg-panel-keylime opacity-0 transition-[transform,opacity] duration-(--duration-moderate) ease-(--ease-out) dark:bg-highlight"
      />
      {NAV.map((group, i) => (
        <div
          key={group.label}
          role="group"
          aria-label={group.label}
          className={cn(i > 0 && "border-t border-rule pt-4")}
        >
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
                    "relative flex h-10 items-center gap-3 rounded-sm px-3 text-sm transition-colors duration-(--duration-quick)",
                    active
                      ? "bg-panel-keylime font-medium text-heading group-data-[pill=on]/nav:bg-transparent dark:bg-highlight"
                      : "text-foreground hover:bg-foreground/6",
                  )}
                >
                  <Icon
                    aria-hidden
                    strokeWidth={1.75}
                    className={cn("size-4", active ? "text-heading" : "text-muted-foreground")}
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
  // A server that is not answering is usually waking or restarting: a wait, not an alarm.
  const label = {
    // The line below says whether a model answers, so this one does not repeat "offline".
    ok: "ARIA is ready",
    degraded: "Some of ARIA is not working",
    down: "Waiting for ARIA's server",
    unknown: "Checking ARIA's server",
  }[state];
  return (
    <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
      <span
        aria-hidden
        className={cn(
          "block size-2 shrink-0 rounded-full",
          state === "ok" && "bg-ok",
          (state === "degraded" || state === "down") && "bg-sev3",
          state === "unknown" && "bg-control",
        )}
      />
      <span>{label}</span>
    </p>
  );
}

/** On a phone the server's status sits in the closed menu, so the page itself says when the server
 * is not answering (FL-07). */
function PhoneServerNotice() {
  const { isError } = useHealth();
  if (!isError) return null;
  return (
    <p className="mb-6 flex items-center gap-2 rounded-card border border-rule bg-raised px-4 py-3 text-sm text-muted-foreground lg:hidden">
      <span aria-hidden className="block size-2 shrink-0 rounded-full bg-sev3" />
      Waiting for ARIA&apos;s server. This page carries on when it answers.
    </p>
  );
}

/** Who answers this visitor's runs and questions, as a link to the key form on Settings. */
function ModelLine({ onNavigate }: { onNavigate?: () => void }) {
  const view = useSettingsView();
  const saved = useModelKey();
  if (!view.data) return null;
  const kinds = view.data.visitor_keys ?? [];
  const access = modelAccess(saved.data?.provider ?? null, kinds, view.data.shared_model);
  return (
    <Link
      href="/console/settings#set-model-key"
      onClick={onNavigate}
      className="inline-flex min-h-6 w-fit items-center text-xs text-muted-foreground underline decoration-control underline-offset-2 hover:text-foreground hover:decoration-foreground"
    >
      {accessShort(access, kinds.length > 0)}
    </Link>
  );
}

function SessionFooter({ onNavigate }: { onNavigate?: () => void }) {
  const { data: session } = useSession();
  const signOut = useSignOut();
  return (
    <div className="grid gap-3 border-t border-rule pt-4">
      <ApiStatus />
      <ModelLine onNavigate={onNavigate} />
      <div className="flex items-center justify-between gap-2">
        {session?.signedIn ? (
          <p className="min-w-0 truncate text-xs text-muted-foreground">
            Signed in as <span className="font-medium text-foreground">{session.name}</span>
          </p>
        ) : (
          <span aria-hidden />
        )}
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

// Pages that need no live API: How ARIA works and the evaluation read recorded files, and the
// guide is mostly words. They stay readable while the API is down, and before anyone signs in.
const WITHOUT_API = new Set(["/console/evals", "/console/guide"]);
const needsNoApi = (pathname: string) =>
  WITHOUT_API.has(pathname) || /^\/console\/how-it-works(\/|$)/.test(pathname);

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

/** True once `ms` have passed since the component mounted. */
function useAfter(ms: number): boolean {
  const [passed, setPassed] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setPassed(true), ms);
    return () => window.clearTimeout(timer);
  }, [ms]);
  return passed;
}

/** What the console shows until ARIA's API answers. A free host puts an idle API to sleep, and
 * the first answer after that takes about a minute, so a failed check reads as "waking up" for a
 * minute and a half before it reads as down. The session check keeps asking meanwhile, so the page
 * carries on by itself once the API answers. */
function Connecting({
  busy,
  failed,
  onRetry,
}: {
  busy: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  const slow = useAfter(4000);
  const gaveUp = useAfter(90_000);
  if (failed && gaveUp) {
    return (
      <div className="grid gap-4">
        <ErrorState
          title="ARIA's API is not answering"
          error={
            new Error(
              "Incidents, reviews and the incident library need it. This page keeps checking, and carries on by itself once it answers.",
            )
          }
          onRetry={onRetry}
        />
        <SelfHosting />
        <p className="text-sm text-muted-foreground">
          These work without it:{" "}
          <Link href="/console/evals" className="underline decoration-control underline-offset-4">
            the test results
          </Link>{" "}
          and{" "}
          <Link href="/console/guide" className="underline decoration-control underline-offset-4">
            the guide
          </Link>
          .
        </p>
      </div>
    );
  }
  return (
    <div className="grid gap-4">
      <div role="status">
        {busy ? (
          <p className="max-w-prose text-sm text-muted-foreground">
            ARIA is busy right now. This page carries on by itself in a few seconds.
          </p>
        ) : slow || failed ? (
          <p className="max-w-prose text-sm text-muted-foreground">
            ARIA&apos;s server is waking up. After a quiet spell this takes up to a minute, and this
            page carries on by itself.
          </p>
        ) : (
          <span className="sr-only">Connecting to ARIA</span>
        )}
      </div>
      {failed && !busy ? <SelfHosting /> : null}
      <Skeleton className="h-10 w-64" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

/** For whoever runs ARIA: folded away, so a visitor reads only what applies to them. */
function SelfHosting() {
  return (
    <details className="text-sm text-muted-foreground">
      <summary className="min-h-6 w-fit cursor-pointer underline decoration-control underline-offset-4">
        Running ARIA yourself?
      </summary>
      <p className="mt-2 max-w-prose">
        Start the API with <code>make dev</code> or <code>docker compose up</code>, and check that
        this web server&apos;s <code>ARIA_API_URL</code> points at it.
      </p>
    </details>
  );
}

function Gate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const session = useSession();
  const open = needsNoApi(pathname);
  const reachable = !session.isError && Boolean(session.data?.reachable);
  const busy = Boolean(session.data?.busy);
  const signedOut = Boolean(session.data?.authRequired && !session.data.signedIn);
  useHashOnArrival(open || (reachable && !busy && !signedOut));
  if (open) return <>{children}</>;
  if (session.isPending || !reachable || busy) {
    return (
      <Connecting
        busy={busy}
        failed={!session.isPending && !reachable}
        onRetry={() => void session.refetch()}
      />
    );
  }
  if (signedOut) return <SignIn />;
  return <>{children}</>;
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  // Set when the menu closes because a page was chosen in it.
  const chose = useRef(false);
  const leave = () => {
    chose.current = true;
    setOpen(false);
  };
  return (
    <ConsoleCommands>
      <a
        href="#console-main"
        className="sr-only z-50 rounded-sm bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <div className="min-h-dvh bg-app lg:grid lg:grid-cols-[17.5rem_minmax(0,1fr)]">
        {/* A floating white panel on the cream page, like the site's navigation bars. */}
        <aside className="hidden p-3 lg:block">
          <div className="sticky top-3 flex h-[calc(100dvh-1.5rem)] flex-col gap-4 rounded-card border border-rule bg-raised px-3 py-5">
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
          <header className="sticky top-0 z-30 bg-app px-3 pt-3 lg:hidden">
            <div className="flex h-14 items-center justify-between gap-3 rounded-card border border-rule bg-raised px-2">
              <Dialog open={open} onOpenChange={setOpen}>
                <DialogTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label="Open navigation">
                    <MenuIcon aria-hidden />
                  </Button>
                </DialogTrigger>
                <SheetContent
                  side="left"
                  closeLabel="Close navigation"
                  // After choosing a page, focus goes to the page, as it does after Search; closed
                  // any other way, it goes back to the menu button.
                  onCloseAutoFocus={(event) => {
                    if (!chose.current) return;
                    chose.current = false;
                    event.preventDefault();
                    document.getElementById("console-main")?.focus({ preventScroll: true });
                  }}
                  // Open on the page being read, so the next Tab or arrow goes somewhere useful.
                  onOpenAutoFocus={(event) => {
                    const sheet = event.currentTarget as HTMLElement | null;
                    const here = sheet?.querySelector<HTMLElement>("nav [aria-current='page']");
                    if (here) {
                      event.preventDefault();
                      here.focus();
                    }
                  }}
                >
                  <DialogTitle className="sr-only">Navigation</DialogTitle>
                  <Link
                    href="/"
                    className="rounded-sm px-1.5"
                    aria-label="ARIA home"
                    onClick={() => setOpen(false)}
                  >
                    <Wordmark />
                  </Link>
                  <div className="-mx-1 flex-1 overflow-y-auto px-1 py-1">
                    <Nav onNavigate={leave} />
                  </div>
                  <SessionFooter onNavigate={leave} />
                </SheetContent>
              </Dialog>
              {/* Every logo goes to the same place: the home page. */}
              <Link href="/" className="rounded-sm" aria-label="ARIA home">
                <Wordmark />
              </Link>
              <div className="flex items-center">
                <PaletteIconButton />
                <ThemeToggle />
              </div>
            </div>
          </header>
          {/* Focusable, so the skip link and a closed command palette can hand it focus. */}
          <main
            id="console-main"
            tabIndex={-1}
            className="mx-auto w-full max-w-[90rem] flex-1 px-4 py-8 outline-none sm:px-6 lg:px-8 lg:py-12"
          >
            <PhoneServerNotice />
            <Gate>{children}</Gate>
          </main>
        </div>
      </div>
    </ConsoleCommands>
  );
}
