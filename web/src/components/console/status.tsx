import {
  BookOpenIcon,
  CircleCheckIcon,
  CircleDashedIcon,
  CircleXIcon,
  LoaderCircleIcon,
  OctagonAlertIcon,
  UserRoundCheckIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

const STATUS: Record<string, { label: string; className: string; icon: typeof CircleCheckIcon }> = {
  queued: { label: "Queued", className: "text-muted-foreground", icon: CircleDashedIcon },
  running: { label: "Running", className: "text-foreground", icon: LoaderCircleIcon },
  awaiting_review: {
    label: "Needs review",
    // A keylime pill, like the waiting banner: the one state that waits on a person, set apart
    // from the plain green text of a published run without taking the main action's forest.
    className:
      "rounded-full bg-panel-keylime px-2 text-heading dark:bg-highlight dark:text-highlight-foreground",
    icon: UserRoundCheckIcon,
  },
  published: { label: "Published", className: "text-ok", icon: CircleCheckIcon },
  rejected: { label: "Discarded", className: "text-muted-foreground", icon: CircleXIcon },
  failed: { label: "Failed", className: "text-danger", icon: OctagonAlertIcon },
};

/** In place of a status on the examples every visitor sees: they never change. */
export function ExampleStatus({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 text-xs whitespace-nowrap text-muted-foreground",
        className,
      )}
    >
      <BookOpenIcon aria-hidden className="size-3.5" />
      Example
    </span>
  );
}

export const STATUS_LABEL = Object.fromEntries(
  Object.entries(STATUS).map(([k, v]) => [k, v.label]),
);

export function RunStatus({ status, className }: { status: string; className?: string }) {
  const spec = STATUS[status] ?? { label: status, className: "", icon: CircleDashedIcon };
  const Icon = spec.icon;
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-xs border border-transparent px-1.5 text-xs font-medium whitespace-nowrap",
        spec.className,
        className,
      )}
    >
      <Icon
        aria-hidden
        className={cn(
          "size-3.5",
          status === "running" && "animate-spin motion-reduce:animate-none",
        )}
      />
      {spec.label}
    </span>
  );
}
