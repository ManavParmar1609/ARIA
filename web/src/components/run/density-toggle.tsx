"use client";

import { useId } from "react";

import { setDensity, useDensity, type Density } from "@/lib/density";
import { cn } from "@/lib/utils";

const CHOICES: { value: Density; label: string }[] = [
  { value: "comfortable", label: "Comfortable" },
  { value: "compact", label: "Compact" },
];

/** Comfortable or compact rows, as two radio buttons that look like one control. */
export function DensityToggle({ className }: { className?: string }) {
  const density = useDensity();
  // Each toggle is its own radio group, so two on one page never uncheck each other.
  const name = useId();
  return (
    <fieldset className={cn("flex items-center gap-2 text-xs", className)}>
      <legend className="sr-only">Row spacing</legend>
      <span aria-hidden className="text-muted-foreground">
        Rows
      </span>
      <span className="inline-flex rounded-md ring-1 ring-rule ring-inset">
        {CHOICES.map((choice) => (
          <label
            key={choice.value}
            className={cn(
              "inline-flex h-7 cursor-pointer items-center px-2.5 first:rounded-l-md last:rounded-r-md has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
              density === choice.value
                ? "bg-highlight font-medium text-highlight-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <input
              type="radio"
              name={name}
              value={choice.value}
              checked={density === choice.value}
              onChange={() => setDensity(choice.value)}
              className="sr-only"
            />
            {choice.label}
          </label>
        ))}
      </span>
    </fieldset>
  );
}
