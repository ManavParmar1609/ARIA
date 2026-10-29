"use client";

import { MonitorIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const subscribe = () => () => {};

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme, resolvedTheme } = useTheme();
  // The stored theme is only known in the browser; render a neutral icon until hydrated.
  const mounted = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  const Icon = !mounted ? MonitorIcon : resolvedTheme === "light" ? SunIcon : MoonIcon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" className={className} aria-label="Change theme">
          <Icon aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuRadioGroup
          value={mounted ? (theme ?? "dark") : "dark"}
          onValueChange={setTheme}
        >
          <DropdownMenuRadioItem value="dark">Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">Match my system</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
