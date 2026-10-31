import type { Metadata } from "next";
import { notFound } from "next/navigation";

// The console layout's title template gives "Page not found | ARIA console".
export const metadata: Metadata = { title: "Page not found" };

// Any console address that matches no page: the console's own not-found page answers, inside the
// console, with its menu still there.
export default function MissingConsolePage() {
  notFound();
}
