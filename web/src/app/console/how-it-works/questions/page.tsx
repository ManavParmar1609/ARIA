import type { Metadata } from "next";

import { QuestionsPart } from "@/components/site/story";

export const metadata: Metadata = { title: "How ARIA works: questions" };

export default function QuestionsPage() {
  return <QuestionsPart />;
}
