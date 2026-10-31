import { notFound } from "next/navigation";

// Any console address that matches no page: the console's own not-found page answers, inside the
// console, with its menu still there.
export default function MissingConsolePage() {
  notFound();
}
