import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden
      // A tint of the text colour, so a placeholder shows on the canvas and on cards alike, by
      // day and at night.
      className={cn(
        "animate-pulse rounded-sm bg-foreground/8 motion-reduce:animate-none",
        className,
      )}
      {...props}
    />
  );
}
