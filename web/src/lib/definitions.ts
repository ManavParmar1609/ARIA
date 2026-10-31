import type { Severity } from "@/lib/api/types";
import { GLOSSARY } from "@/lib/glossary";
import { LEVEL_RESPONSE, LEVEL_WORD } from "@/lib/levels";

// "What does SEV1 mean?" asks for a word's meaning, which ARIA's word list answers better than a
// search of past incidents (which once answered it with an unrelated ZooKeeper incident).

export interface Definition {
  term: string;
  text: string;
}

const LEVELS: Severity[] = ["SEV1", "SEV2", "SEV3", "SEV4"];

// "What does X mean?", "What is a X?", "What's X?", "Define X", "Meaning of X".
const ASKS =
  /^\s*(?:what(?:'s|’s|\s+is|\s+are|\s+does|\s+do)|define|meaning\s+of|explain)\s+(?:an?\s+|the\s+)?(.+?)(?:\s+(?:mean|means|stand\s+for))?\s*[?.!]*\s*$/i;

function level(sev: Severity): string {
  return `${sev} means ${LEVEL_WORD[sev]}. ${LEVEL_RESPONSE[sev]}`;
}

/** The names a glossary entry answers to: "Short list (prediction set)" answers to both. */
function namesOf(key: string, term: string): string[] {
  const lower = term.toLowerCase();
  const inside = /\(([^)]+)\)/.exec(lower)?.[1];
  const outside = lower.replace(/\s*\([^)]*\)/, "").trim();
  return [lower, outside, inside ?? "", key.replaceAll("-", " ")].filter(Boolean);
}

/** The meaning of the word a question asks about, when ARIA's word list has it; else null. */
export function definitionFor(question: string): Definition | null {
  const asked = ASKS.exec(question)?.[1]
    ?.toLowerCase()
    .replace(/["“”‘’']/g, "")
    .trim();
  if (!asked) return null;
  const one = /^sev\s*-?\s*([1-4])$/.exec(asked);
  if (one) {
    const sev = `SEV${one[1]}` as Severity;
    return { term: sev, text: level(sev) };
  }
  if (/^(?:the\s+)?(?:sev|severity)(?:\s+levels?)?(?:\s+\d(?:\s*(?:to|-|–)\s*\d)?)?$/.test(asked)) {
    return {
      term: "Severity levels",
      text: LEVELS.map(level).join(" "),
    };
  }
  const wanted = new Set([asked, asked.replace(/e?s$/, "")]);
  for (const [key, entry] of Object.entries(GLOSSARY)) {
    if (namesOf(key, entry.term).some((name) => wanted.has(name))) {
      return { term: entry.term, text: entry.definition };
    }
  }
  return null;
}
