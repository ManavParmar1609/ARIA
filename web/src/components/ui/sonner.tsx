"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";

export function Toaster() {
  const { resolvedTheme } = useTheme();
  return (
    <Sonner
      theme={resolvedTheme === "light" ? "light" : "dark"}
      position="bottom-right"
      closeButton
      toastOptions={{
        classNames: {
          toast: "!rounded-md !border !border-rule !bg-raised !text-foreground !font-sans",
          description: "!text-muted-foreground",
        },
      }}
    />
  );
}
