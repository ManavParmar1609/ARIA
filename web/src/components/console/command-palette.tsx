"use client";

import {
  BookOpenIcon,
  CompassIcon,
  PlugIcon,
  CornerDownLeftIcon,
  FlaskConicalIcon,
  HomeIcon,
  InboxIcon,
  KeyboardIcon,
  LibraryIcon,
  LogOutIcon,
  MessageSquareTextIcon,
  MonitorIcon,
  MoonIcon,
  PlayIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  SunIcon,
  TextQuoteIcon,
  UserRoundCheckIcon,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import { SeverityBadge } from "@/components/aria/severity";
import { runTitle } from "@/components/console/run-row";
import { STATUS_LABEL } from "@/components/console/status";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  useRunbooks,
  useRuns,
  useScenarios,
  useSession,
  useSignOut,
  useStartSample,
} from "@/lib/api/hooks";
import { isSeverity } from "@/lib/api/types";
import { GLOSSARY } from "@/lib/glossary";
import { GO_KEYS, isTypingTarget, setShortcutsEnabled, useShortcutsEnabled } from "@/lib/shortcuts";
import { systemName } from "@/lib/systems";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

interface Commands {
  openPalette: () => void;
  openHelp: () => void;
}

const CommandsContext = createContext<Commands>({ openPalette: () => {}, openHelp: () => {} });

/** Open the command palette or the shortcuts sheet from anywhere in the console. */
export function useCommands(): Commands {
  return useContext(CommandsContext);
}

type Group = "Pages" | "Incidents" | "Samples" | "Runbooks" | "Words" | "Actions";
const GROUPS: Group[] = ["Pages", "Incidents", "Samples", "Runbooks", "Words", "Actions"];

interface Item {
  id: string;
  group: Group;
  label: string;
  /** A second line: what a page is for, an incident's state, a word's meaning. */
  hint?: string;
  /** More words to match on, not shown. */
  keywords?: string;
  icon: LucideIcon;
  badge?: ReactNode;
  run: () => void;
}

const PAGES: { href: string; label: string; hint: string; icon: LucideIcon; keywords?: string }[] =
  [
    {
      href: "/console/runs",
      label: "Incidents",
      hint: "Every incident ARIA has triaged, newest first",
      icon: InboxIcon,
      keywords: "run runs queue list triaged",
    },
    {
      href: "/console/runs?status=awaiting_review",
      label: "Incidents that need review",
      hint: "Reports waiting for a person",
      icon: UserRoundCheckIcon,
      keywords: "approve pending",
    },
    {
      href: "/console/runs/new",
      label: "New triage",
      hint: "Paste logs or start from a sample",
      icon: PlusIcon,
      keywords: "create start paste logs",
    },
    {
      href: "/console/ask",
      label: "Ask ARIA",
      hint: "Questions about an incident, past incidents and runbooks",
      icon: MessageSquareTextIcon,
      keywords: "question answer sources",
    },
    {
      href: "/console/memory",
      label: "Incident library",
      hint: "Search past incidents by meaning",
      icon: LibraryIcon,
      keywords: "memory search history similar past",
    },
    {
      href: "/console/runbooks",
      label: "Runbooks",
      hint: "The steps ARIA may propose",
      icon: BookOpenIcon,
      keywords: "playbook mitigation",
    },
    {
      href: "/console/evals",
      label: "Test results",
      hint: "How ARIA was tested, and where it falls short",
      icon: FlaskConicalIcon,
      keywords: "evaluation accuracy metrics results",
    },
    {
      href: "/console/guide",
      label: "Guide",
      hint: "First steps, how to read an incident, the words",
      icon: CompassIcon,
      keywords: "help how to use tour",
    },
    {
      href: "/console/guide/connect",
      label: "Connect ARIA to your systems",
      hint: "Alerts, the command line, other agents, message channels, triage in chat",
      icon: PlugIcon,
      keywords: "alertmanager grafana webhook a2a agui chat mcp cli slack teams integrations",
    },
    {
      href: "/console/settings",
      label: "Settings",
      hint: "Your model key, theme and session",
      icon: SettingsIcon,
      keywords:
        "preferences providers theme key keys api model language llm claude anthropic gemini google openai gpt nvidia nim",
    },
    {
      href: "/",
      label: "ARIA home page",
      hint: "The landing page and the recorded run",
      icon: HomeIcon,
      keywords: "landing website",
    },
  ];

function matches(item: Item, words: string[]): boolean {
  const hay = `${item.label} ${item.hint ?? ""} ${item.keywords ?? ""}`.toLowerCase();
  return words.every((w) => hay.includes(w));
}

/** A title that starts with the query beats one that contains it, which beats a hint match. */
function score(item: Item, words: string[]): number {
  const label = item.label.toLowerCase();
  if (label.startsWith(words.join(" "))) return 3;
  return words.every((w) => label.includes(w)) ? 2 : 1;
}

function Palette({
  onClose,
  onLeave,
  onHelp,
}: {
  onClose: () => void;
  /** Close for a command that opens another page: that page's content takes focus. */
  onLeave: () => void;
  onHelp: () => void;
}) {
  const router = useRouter();
  const runs = useRuns("all", 30);
  // The samples the server offers, under the names New triage gives them.
  const scenarios = useScenarios();
  const runbooks = useRunbooks();
  const start = useStartSample();
  const session = useSession();
  const signOut = useSignOut();
  const { setTheme } = useTheme();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const list = useRef<HTMLDivElement>(null);

  const go = useCallback(
    (href: string) => {
      onLeave();
      router.push(href as never);
    },
    [onLeave, router],
  );

  const items = useMemo<Item[]>(() => {
    const all: Item[] = PAGES.map((page) => ({
      id: `page:${page.href}`,
      group: "Pages",
      label: page.label,
      hint: page.hint,
      keywords: page.keywords,
      icon: page.icon,
      run: () => go(page.href),
    }));
    for (const run of runs.data?.runs ?? []) {
      all.push({
        id: `run:${run.id}`,
        group: "Incidents",
        label: runTitle(run),
        hint: `${systemName(run.system)}, ${STATUS_LABEL[run.status] ?? run.status}`,
        keywords: `${run.id} ${run.system} ${run.severity ?? ""} ${run.status}`,
        icon: InboxIcon,
        badge: isSeverity(run.severity) ? (
          <SeverityBadge severity={run.severity} size="sm" />
        ) : null,
        run: () => go(`/console/runs/${encodeURIComponent(run.id)}`),
      });
    }
    for (const sample of scenarios.data ?? []) {
      all.push({
        id: `sample:${sample.id}`,
        group: "Samples",
        label: `Triage a sample: ${sample.title}`,
        hint: `${sample.technology}${sample.benign ? ", harmless" : ""}`,
        keywords: `sample demo try example ${systemName(sample.system)} ${sample.summary}`,
        icon: PlayIcon,
        run: () => {
          onLeave();
          // The palette closes at once, so the answer is awaited here rather than in mutate's
          // own callbacks, which are dropped once the palette is gone. A note bridges the
          // second before the incident page opens; the page then says the run has started.
          const note = toast.loading(`Starting "${sample.title}"`);
          start
            .mutateAsync({
              id: sample.id,
              body: {
                servers: null,
                rate: null,
                options: { use_llm: true, investigate: true, require_approval: true },
              },
            })
            .then((accepted) => {
              toast.dismiss(note);
              router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
            })
            .catch((error: Error) =>
              toast.error("The sample could not be started", {
                id: note,
                description: error.message,
              }),
            );
        },
      });
    }
    for (const book of runbooks.data ?? []) {
      all.push({
        id: `runbook:${book.slug}`,
        group: "Runbooks",
        label: book.title,
        hint: book.when_to_use,
        keywords: `runbook playbook steps fix ${book.slug} ${book.systems.map(systemName).join(" ")}`,
        icon: BookOpenIcon,
        run: () => go(`/console/runbooks/${encodeURIComponent(book.slug)}`),
      });
    }
    for (const [key, entry] of Object.entries(GLOSSARY)) {
      all.push({
        id: `word:${key}`,
        group: "Words",
        label: entry.term,
        hint: entry.definition,
        keywords: "glossary define meaning word",
        icon: TextQuoteIcon,
        run: () => go("/console/guide#words"),
      });
    }
    all.push(
      {
        id: "act:light",
        group: "Actions",
        label: "Use the light theme",
        icon: SunIcon,
        keywords: "theme colour appearance",
        run: () => {
          setTheme("light");
          onClose();
        },
      },
      {
        id: "act:dark",
        group: "Actions",
        label: "Use the dark theme",
        icon: MoonIcon,
        keywords: "theme colour appearance night",
        run: () => {
          setTheme("dark");
          onClose();
        },
      },
      {
        id: "act:system",
        group: "Actions",
        label: "Match my system's theme",
        icon: MonitorIcon,
        keywords: "theme colour appearance auto",
        run: () => {
          setTheme("system");
          onClose();
        },
      },
      {
        id: "act:keys",
        group: "Actions",
        label: "Show keyboard shortcuts",
        icon: KeyboardIcon,
        keywords: "help keys hotkeys",
        run: () => {
          onClose();
          onHelp();
        },
      },
    );
    if (session.data?.signedIn) {
      all.push({
        id: "act:signout",
        group: "Actions",
        label: "Sign out",
        icon: LogOutIcon,
        keywords: "logout leave",
        run: () => {
          onClose();
          signOut.mutate();
        },
      });
    }
    return all;
  }, [
    runs.data,
    scenarios.data,
    runbooks.data,
    session.data,
    go,
    start,
    router,
    onClose,
    onLeave,
    onHelp,
    setTheme,
    signOut,
  ]);

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      // Without a query: the pages, a few recent incidents, the samples and the actions.
      let incidents = 0;
      return items.filter((item) => {
        if (item.group === "Words" || item.group === "Runbooks") return false;
        if (item.group === "Incidents") return ++incidents <= 5;
        return true;
      });
    }
    // Keep the groups in order (the list is drawn group by group), best matches first in each.
    return items
      .filter((item) => matches(item, words))
      .map((item, i) => ({ item, i, g: GROUPS.indexOf(item.group), s: score(item, words) }))
      .sort((a, b) => a.g - b.g || b.s - a.s || a.i - b.i)
      .map(({ item }) => item)
      .slice(0, 40);
  }, [items, query]);

  const activeIndex = Math.min(active, Math.max(0, shown.length - 1));
  const optionId = (i: number) => `${listId}-option-${i}`;

  useEffect(() => {
    document.getElementById(optionId(activeIndex))?.scrollIntoView({ block: "nearest" });
    // optionId only depends on listId, which never changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (shown.length === 0) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((activeIndex + step + shown.length) % shown.length);
    } else if (event.key === "Home" && event.ctrlKey) {
      setActive(0);
    } else if (event.key === "End" && event.ctrlKey) {
      setActive(shown.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      shown[activeIndex]?.run();
    }
  };

  let index = -1;
  return (
    <>
      <div className="flex items-center gap-3 border-b border-rule px-5">
        <SearchIcon aria-hidden className="size-5 shrink-0 text-muted-foreground" />
        {/* The dialog moves focus here when it opens: it is the first thing that takes focus. */}
        <input
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={shown.length ? optionId(activeIndex) : undefined}
          aria-label="Search pages, incidents, samples, runbooks, words and actions"
          placeholder="Jump to a page, an incident, a sample…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          className="h-16 min-w-0 flex-1 bg-transparent text-lg text-foreground outline-none placeholder:text-muted-foreground"
        />
        <kbd className="hidden rounded-xs border border-control/60 px-1.5 py-0.5 text-xs text-muted-foreground sm:inline">
          Esc
        </kbd>
      </div>
      <div
        ref={list}
        id={listId}
        role="listbox"
        aria-label="Results"
        className="max-h-[min(60vh,32rem)] overflow-y-auto p-2"
      >
        {shown.length === 0 ? (
          <p className="px-3 py-8 text-center text-muted-foreground" role="status">
            Nothing matches “{query}”. Try a page name, an incident, or a word such as “prediction
            set”.
          </p>
        ) : (
          GROUPS.map((group) => {
            const inGroup = shown.filter((item) => item.group === group);
            if (inGroup.length === 0) return null;
            const headingId = `${listId}-${group}`;
            return (
              <div key={group} role="group" aria-labelledby={headingId} className="pb-1">
                <div
                  id={headingId}
                  role="presentation"
                  className="px-3 pt-3 pb-1.5 text-sm font-medium text-muted-foreground"
                >
                  {group}
                </div>
                {inGroup.map((item) => {
                  index += 1;
                  const i = index;
                  const Icon = item.icon;
                  const selected = i === activeIndex;
                  return (
                    // Keyboard selection goes through the input (aria-activedescendant), as the
                    // ARIA combobox pattern asks; options take clicks but never focus.
                    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus
                    <div
                      key={item.id}
                      id={optionId(i)}
                      role="option"
                      aria-selected={selected}
                      onMouseMove={() => setActive(i)}
                      onClick={() => item.run()}
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2.5",
                        selected
                          ? "bg-panel-keylime text-heading dark:bg-highlight"
                          : "text-foreground",
                      )}
                    >
                      <Icon aria-hidden className="size-4 shrink-0" strokeWidth={1.75} />
                      <span className="grid min-w-0 flex-1">
                        <span className="truncate">{item.label}</span>
                        {item.hint ? (
                          <span
                            className={cn(
                              "truncate text-sm",
                              selected ? "text-heading" : "text-muted-foreground",
                            )}
                          >
                            {item.hint}
                          </span>
                        ) : null}
                      </span>
                      {item.badge}
                      {selected ? (
                        <CornerDownLeftIcon aria-hidden className="size-4 shrink-0" />
                      ) : null}
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-rule px-5 py-3 text-sm text-muted-foreground">
        {/* Keys mean nothing on a touch screen, where a tap opens a result. */}
        <span className="[@media(pointer:coarse)]:hidden">Arrow keys to move, Enter to open</span>
        <button
          type="button"
          onClick={() => {
            onClose();
            onHelp();
          }}
          className="link"
        >
          Keyboard shortcuts
        </button>
      </div>
    </>
  );
}

function Key({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-7 min-w-7 items-center justify-center rounded-sm border border-control/60 bg-raised px-1.5 text-sm font-medium text-foreground">
      {children}
    </kbd>
  );
}

function ShortcutsHelp() {
  const enabled = useShortcutsEnabled();
  const switchId = useId();
  return (
    <div className="grid gap-5">
      <dl className="grid gap-x-6 gap-y-2.5 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="flex items-center gap-1">
          <Key>Ctrl</Key>
          <span aria-hidden>or</span>
          <Key>⌘</Key>
          <Key>K</Key>
        </dt>
        <dd className="self-center text-muted-foreground">Open search</dd>
        <dt>
          <Key>/</Key>
        </dt>
        <dd className="self-center text-muted-foreground">Open search</dd>
        <dt>
          <Key>?</Key>
        </dt>
        <dd className="self-center text-muted-foreground">Show these shortcuts</dd>
        {GO_KEYS.map((go) => (
          <div key={go.key} className="contents">
            <dt className="flex items-center gap-1">
              <Key>g</Key>
              <span aria-hidden className="text-muted-foreground">
                then
              </span>
              <Key>{go.key}</Key>
            </dt>
            <dd className="self-center text-muted-foreground">Go to {go.label}</dd>
          </div>
        ))}
      </dl>
      <div className="flex items-start justify-between gap-4 rounded-md bg-sunken p-4">
        <div className="grid gap-1">
          <label htmlFor={switchId} className="text-sm font-medium">
            Single-key shortcuts
          </label>
          <p className="text-sm text-muted-foreground">
            Turn these off if they get in the way of speech input or a screen reader. Ctrl or ⌘ + K
            always works. Approving a report never has a shortcut.
          </p>
        </div>
        <Switch id={switchId} checked={enabled} onCheckedChange={setShortcutsEnabled} />
      </div>
    </div>
  );
}

/**
 * The console's keyboard layer: the command palette (Ctrl or Cmd + K, or "/"), a sheet of
 * shortcuts ("?"), and "g" then a letter to go to a page. Single-key shortcuts never fire while
 * typing in a field, and can be turned off (WCAG 2.1.4).
 */
export function ConsoleCommands({ children }: { children: ReactNode }) {
  const router = useRouter();
  const enabled = useShortcutsEnabled();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const pendingG = useRef(0);
  // Neither dialog has a button of its own (a shortcut or a search button opens them), so they
  // remember what had focus and give it back when they close. After a command that opens a page,
  // the page's content takes focus instead, as it does with nothing focused before.
  const opener = useRef<HTMLElement | null>(null);
  const toPage = useRef(false);
  const remember = useCallback(() => {
    const active = document.activeElement;
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
    toPage.current = false;
  }, []);
  const showPalette = useCallback(() => {
    remember();
    setHelp(false);
    setPalette(true);
  }, [remember]);
  const giveFocusBack = useCallback((event: Event) => {
    event.preventDefault();
    const back =
      !toPage.current && opener.current?.isConnected
        ? opener.current
        : document.getElementById("console-main");
    back?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (palette) setPalette(false);
        else showPalette();
        return;
      }
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (!enabled || palette || help || isTypingTarget(event.target)) return;
      if (event.key === "/") {
        event.preventDefault();
        showPalette();
      } else if (event.key === "?") {
        event.preventDefault();
        remember();
        setHelp(true);
      } else if (event.key === "g") {
        pendingG.current = Date.now();
      } else if (pendingG.current && Date.now() - pendingG.current < 1200) {
        pendingG.current = 0;
        const go = GO_KEYS.find((g) => g.key === event.key);
        if (go) {
          event.preventDefault();
          router.push(go.href as never);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, palette, help, router, remember, showPalette]);

  const commands = useMemo<Commands>(
    () => ({
      openPalette: showPalette,
      openHelp: () => {
        remember();
        setHelp(true);
      },
    }),
    [remember, showPalette],
  );
  const closePalette = useCallback(() => setPalette(false), []);
  const leavePalette = useCallback(() => {
    toPage.current = true;
    setPalette(false);
  }, []);
  const openHelp = useCallback(() => setHelp(true), []);

  return (
    <CommandsContext.Provider value={commands}>
      {children}
      <Dialog open={palette} onOpenChange={setPalette}>
        <DialogContent
          instant
          onCloseAutoFocus={giveFocusBack}
          closeLabel="Close search"
          className="top-[12vh] max-w-2xl translate-y-0 gap-0 overflow-hidden p-0 [&>button:last-child]:hidden"
        >
          <DialogTitle className="sr-only">Search</DialogTitle>
          <DialogDescription className="sr-only">
            Type to find a page, an incident, a sample, a runbook or a word, then press Enter.
          </DialogDescription>
          {palette ? (
            <Palette onClose={closePalette} onLeave={leavePalette} onHelp={openHelp} />
          ) : null}
        </DialogContent>
      </Dialog>
      <Dialog open={help} onOpenChange={setHelp}>
        <DialogContent
          instant
          onCloseAutoFocus={giveFocusBack}
          closeLabel="Close the shortcuts"
          className="max-w-xl"
        >
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>
            Move around the console without the mouse. Shortcuts wait while you type in a field.
          </DialogDescription>
          <ShortcutsHelp />
        </DialogContent>
      </Dialog>
    </CommandsContext.Provider>
  );
}
