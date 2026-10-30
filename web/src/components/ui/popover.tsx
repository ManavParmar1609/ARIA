"use client";

import { HoverCard as HoverCardPrimitive } from "radix-ui";
import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

// Panels open without a fade, so their text is at full contrast from the first frame.
const panel =
  "z-50 w-80 max-w-[calc(100vw-2rem)] rounded-md border border-rule bg-raised p-4 text-sm text-foreground outline-none origin-(--radix-hover-card-content-transform-origin) ease-(--ease-out) data-[state=open]:animate-in data-[state=open]:zoom-in-[0.98] data-[state=closed]:animate-out data-[state=closed]:fade-out-0";

export const HoverCard = HoverCardPrimitive.Root;
export const HoverCardTrigger = HoverCardPrimitive.Trigger;

export function HoverCardContent({
  className,
  align = "start",
  sideOffset = 6,
  ...props
}: ComponentProps<typeof HoverCardPrimitive.Content>) {
  return (
    <HoverCardPrimitive.Portal>
      <HoverCardPrimitive.Content
        data-slot="hover-card-content"
        align={align}
        sideOffset={sideOffset}
        className={cn(panel, className)}
        {...props}
      />
    </HoverCardPrimitive.Portal>
  );
}
