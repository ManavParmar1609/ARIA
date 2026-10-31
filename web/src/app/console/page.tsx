import { redirect } from "next/navigation";

// The console opens where visitors act: picking an incident to triage.
export default function ConsoleHome() {
  redirect("/console/runs/new");
}
