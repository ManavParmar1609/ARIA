"use client";

import { useEffect } from "react";

/** Name the browser tab after what the page shows once it has loaded (the server only knows
 * the ID), in the console's "%s | ARIA console" form. */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (title) document.title = `${title} | ARIA console`;
  }, [title]);
}
