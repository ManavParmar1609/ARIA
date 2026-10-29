"use client";

import { Tabs as TabsPrimitive } from "radix-ui";
import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        "flex [scrollbar-width:none] items-end gap-1 overflow-x-auto border-b border-rule",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative -mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 border-transparent px-3 text-sm font-medium text-muted-foreground transition-colors duration-(--duration-quick) hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("pt-5 outline-none", className)}
      {...props}
    />
  );
}
