"use client";

import { CheckIcon } from "lucide-react";
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
          "z-50 min-w-44 origin-(--radix-dropdown-menu-content-transform-origin) rounded-md border border-rule bg-raised p-1 text-foreground duration-(--duration-quick) ease-(--ease-out) data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.97]",
          className,
        )}
        {...props}
      />
    </MenuPrimitive.Portal>
  );
}

const item =
  "relative flex h-9 cursor-default items-center gap-2 rounded-sm px-2 text-sm outline-none select-none data-[disabled]:opacity-50 data-[highlighted]:bg-sunken [&_svg]:size-4 [&_svg]:text-muted-foreground";

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

/** An option that is on or off; the box shows its edge either way, so it reads as a checkbox. */
export function DropdownMenuCheckboxItem({
  className,
  children,
  ...props
}: ComponentProps<typeof MenuPrimitive.CheckboxItem>) {
  return (
    <MenuPrimitive.CheckboxItem className={cn(item, "pl-8", className)} {...props}>
      <span
        aria-hidden
        className="absolute left-2 flex size-4 items-center justify-center rounded-xs border border-control"
      >
        <MenuPrimitive.ItemIndicator>
          <CheckIcon className="size-3 text-heading!" strokeWidth={2.5} />
        </MenuPrimitive.ItemIndicator>
      </span>
      {children}
    </MenuPrimitive.CheckboxItem>
  );
}

export function DropdownMenuSeparator({
  className,
  ...props
}: ComponentProps<typeof MenuPrimitive.Separator>) {
  return <MenuPrimitive.Separator className={cn("my-1 h-px bg-rule", className)} {...props} />;
}
