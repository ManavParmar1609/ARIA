"use client";

import { DropdownMenu as MenuPrimitive } from "radix-ui";
import { type ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const DropdownMenu = MenuPrimitive.Root;
export const DropdownMenuTrigger = MenuPrimitive.Trigger;
export const DropdownMenuRadioGroup = MenuPrimitive.RadioGroup;

export function DropdownMenuContent({
  className,
  sideOffset = 6,
  align = "end",
  ...props
}: ComponentProps<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        data-slot="dropdown-menu-content"
        sideOffset={sideOffset}
        align={align}
        className={cn(
          "z-50 min-w-44 rounded-md border border-rule bg-raised p-1 text-foreground shadow-xl shadow-black/25 data-[state=open]:animate-in data-[state=open]:fade-in-0",
          className,
        )}
        {...props}
      />
    </MenuPrimitive.Portal>
  );
}

const item =
  "relative flex h-9 cursor-default items-center gap-2 rounded-sm px-2 text-sm outline-none select-none data-[disabled]:opacity-50 data-[highlighted]:bg-sunken [&_svg]:size-4 [&_svg]:text-muted-foreground";

export function DropdownMenuItem({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Item>) {
  return <MenuPrimitive.Item className={cn(item, className)} {...props} />;
}

export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.RadioItem>) {
  return (
    <MenuPrimitive.RadioItem className={cn(item, "pl-8", className)} {...props}>
      <span className="absolute left-2 flex size-4 items-center justify-center">
        <MenuPrimitive.ItemIndicator>
          <span className="block size-2 rounded-full bg-foreground" />
        </MenuPrimitive.ItemIndicator>
      </span>
      {children}
    </MenuPrimitive.RadioItem>
  );
}

export function DropdownMenuLabel({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Label>) {
  return (
    <MenuPrimitive.Label
      className={cn("px-2 py-1.5 text-xs font-medium text-muted-foreground", className)}
      {...props}
    />
  );
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn("my-1 h-px bg-rule", className)} {...props} />;
}
