"use client";

import { CheckIcon, ChevronDownIcon, XIcon } from "lucide-react";
import { useId, type ReactNode } from "react";

/** The filters' place on the page, where focus goes once a control that cleared them is gone. */
export const FILTERS_ID = "library-filters";

/** Put focus on the first filter, after the control that held it went away with the filters. */
export function focusFilters() {
  requestAnimationFrame(() =>
    document.querySelector<HTMLElement>(`#${FILTERS_ID} button`)?.focus(),
  );
}

import { SEVERITY_BG } from "@/components/aria/severity";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { isSeverity, type IncidentOut } from "@/lib/api/types";
import { listed } from "@/lib/format";
import { LEVEL_WORD } from "@/lib/levels";
import {
  activeDimensions,
  filterOptions,
  matches,
  NO_FILTERS,
  toggled,
  type FilterOption,
  type Filters,
  type ListDimension,
} from "@/lib/library";
import { cn } from "@/lib/utils";

/**
 * The library's filters: severity as four chips, system and kind of failure as lists (there are
 * too many for chips), where an incident came from, and whether it has a runbook. Each option says
 * how many incidents it would show, counted with the other filters on.
 */
export function LibraryFilters({
  library,
  filters,
  onChange,
}: {
  library: IncidentOut[];
  filters: Filters;
  onChange: (next: Filters) => void;
}) {
  const id = useId();
  const options = (dimension: ListDimension) => filterOptions(library, filters, dimension);
  const toggle = (dimension: ListDimension) => (value: string) =>
    onChange(toggled(filters, dimension, value));
  const withRunbook = library.filter(
    (incident) => incident.runbook_slug && matches(incident, filters, "runbook"),
  ).length;
  const active = activeDimensions(filters).length > 0;
  return (
    <div id={FILTERS_ID} className="grid gap-5">
      <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
        <ChipGroup id={`${id}-sev`} label="Severity">
          {options("severity").map((option) => (
            <Chip
              key={option.value}
              pressed={option.chosen}
              count={option.count}
              onPress={() => toggle("severity")(option.value)}
            >
              {isSeverity(option.value) ? (
                <span
                  aria-hidden
                  className={cn(
                    "block size-2.5 rounded-full border border-sev-edge",
                    SEVERITY_BG[option.value],
                  )}
                />
              ) : null}
              <span className="font-semibold">{option.value}</span>{" "}
              {isSeverity(option.value) ? (
                <span className="text-muted-foreground">{LEVEL_WORD[option.value]}</span>
              ) : null}
            </Chip>
          ))}
        </ChipGroup>
        <ChipGroup id={`${id}-from`} label="Where it came from">
          {options("origin").map((option) => (
            <Chip
              key={option.value}
              pressed={option.chosen}
              count={option.count}
              onPress={() => toggle("origin")(option.value)}
            >
              {option.name}
            </Chip>
          ))}
        </ChipGroup>
      </div>
      <div className="grid grid-cols-2 items-end gap-x-3 gap-y-4 sm:flex sm:flex-wrap sm:gap-x-4">
        <ChecklistFilter
          label="System"
          all="All systems"
          noun={["system", "systems"]}
          options={options("system")}
          onToggle={toggle("system")}
          onClear={() => onChange({ ...filters, system: [] })}
        />
        <ChecklistFilter
          label="Kind of failure"
          all="All kinds"
          noun={["kind", "kinds"]}
          options={options("kind")}
          onToggle={toggle("kind")}
          onClear={() => onChange({ ...filters, kind: [] })}
          wide
        />
        <div className="col-span-2 flex flex-wrap items-center gap-x-4 gap-y-2 sm:pb-0.5">
          <Chip
            pressed={filters.runbook}
            count={withRunbook}
            onPress={() => onChange({ ...filters, runbook: !filters.runbook })}
          >
            Has a runbook
          </Chip>
          {active ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-9"
              onClick={() => {
                onChange(NO_FILTERS);
                focusFilters();
              }}
            >
              <XIcon aria-hidden />
              Clear filters
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ChipGroup({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div role="group" aria-labelledby={id} className="grid gap-1.5">
      <span id={id} className="text-sm font-medium">
        {label}
      </span>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

/** A filter that is on or off, with how many incidents it shows. A tick joins it when it is on,
 * so the state never rests on colour alone. */
function Chip({
  pressed,
  count,
  onPress,
  children,
}: {
  pressed: boolean;
  count: number;
  onPress: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onPress}
      className={cn(
        "inline-flex min-h-9 items-center gap-2 rounded-full px-3.5 text-sm text-heading transition-[background-color,box-shadow] duration-(--duration-quick) ease-(--ease-out)",
        pressed
          ? "bg-highlight text-highlight-foreground ring-2 ring-primary ring-inset"
          : "bg-raised ring-1 ring-rule ring-inset hover:bg-sunken hover:ring-control",
      )}
    >
      {pressed ? <CheckIcon aria-hidden className="-ml-1 size-4" strokeWidth={2.25} /> : null}
      {children}{" "}
      <span className="tabular text-xs text-muted-foreground">
        {count}
        <span className="sr-only"> {count === 1 ? "incident" : "incidents"}</span>
      </span>
    </button>
  );
}

/** Several values of one filter, chosen from a list: the systems or the kinds of failure. */
function ChecklistFilter({
  label,
  all,
  noun,
  options,
  onToggle,
  onClear,
  wide = false,
}: {
  label: string;
  all: string;
  noun: [string, string];
  options: FilterOption[];
  onToggle: (value: string) => void;
  onClear: () => void;
  wide?: boolean;
}) {
  const id = useId();
  const chosen = options.filter((option) => option.chosen);
  const summary =
    chosen.length === 0
      ? all
      : chosen.length <= 2
        ? listed(chosen.map((option) => option.name))
        : `${chosen.length} ${noun[1]}`;
  const keep = (event: Event) => event.preventDefault(); // stays open for the next choice
  return (
    <div className={cn("grid min-w-0 gap-1.5 sm:w-56", wide && "sm:w-64")}>
      <span id={`${id}-label`} className="text-sm font-medium">
        {label}
      </span>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            id={`${id}-value`}
            aria-labelledby={`${id}-label ${id}-value`}
            className={cn(
              "flex h-10 w-full items-center justify-between gap-2 rounded-md border px-3 text-left text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
              chosen.length
                ? "border-primary bg-highlight text-highlight-foreground"
                : "border-control bg-sunken text-foreground",
            )}
          >
            <span className="min-w-0 truncate">{summary}</span>
            <ChevronDownIcon aria-hidden className="size-4 shrink-0 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="start"
          collisionPadding={16}
          className="max-h-(--radix-dropdown-menu-content-available-height) w-(--radix-dropdown-menu-trigger-width) min-w-64 overflow-y-auto"
        >
          <DropdownMenuCheckboxItem
            checked={chosen.length === 0}
            onCheckedChange={onClear}
            onSelect={keep}
          >
            <span className="flex-1">{all}</span>
          </DropdownMenuCheckboxItem>
          <DropdownMenuSeparator />
          {options.map((option) => (
            <DropdownMenuCheckboxItem
              key={option.value}
              checked={option.chosen}
              onCheckedChange={() => onToggle(option.value)}
              onSelect={keep}
            >
              <span className="min-w-0 flex-1 truncate">{option.name}</span>{" "}
              <span className="tabular text-xs text-muted-foreground">
                {option.count}
                <span className="sr-only"> {option.count === 1 ? "incident" : "incidents"}</span>
              </span>
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
