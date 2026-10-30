import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Table({ className, ...props }: ComponentProps<"table">) {
  // The wrapper scrolls on narrow screens, so it takes focus (keyboard users can scroll it).
  // Inline-size containment keeps a wide table from widening the page instead of scrolling.
  return (
    <div
      className="relative w-full overflow-x-auto [contain:inline-size]"
      tabIndex={0}
      role="region"
      aria-label={props["aria-label"] ?? "Table"}
    >
      <table
        className={cn("w-full caption-bottom border-collapse text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function TableHeader({ className, ...props }: ComponentProps<"thead">) {
  return <thead className={cn("[&_tr]:border-b [&_tr]:border-rule", className)} {...props} />;
}

export function TableBody({ className, ...props }: ComponentProps<"tbody">) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

export function TableRow({ className, ...props }: ComponentProps<"tr">) {
  return <tr className={cn("border-b border-rule transition-colors", className)} {...props} />;
}

export function TableHead({ className, scope, ...props }: ComponentProps<"th">) {
  return (
    <th
      scope={scope}
      className={cn(
        "px-3 text-left align-middle",
        // A row header names its row, so it reads like the cells beside it; a column header is
        // the small grey label above a column.
        scope === "row"
          ? "py-3 text-sm font-normal text-foreground"
          : "h-10 text-xs font-medium whitespace-nowrap text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: ComponentProps<"td">) {
  return <td className={cn("px-3 py-3 align-middle", className)} {...props} />;
}
