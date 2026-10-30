// A visitor's own model key, as the console sees it. The key itself stays in an HttpOnly cookie
// (see src/app/api/model-key/route.ts); pages only ever learn its provider and last four characters.

export interface SavedModelKey {
  provider: string | null;
  ending: string | null;
}

/** What the provider said when the ARIA API checked a key. */
export interface ModelKeyCheck {
  provider: string;
  accepted: boolean;
  model: string;
  detail: string;
}

/** Each kind of key ARIA can take: how it reads, and where a visitor gets one. */
export const MODEL_KEYS: Record<string, { label: string; company: string; href: string }> = {
  claude: { label: "Claude", company: "Anthropic", href: "https://console.anthropic.com/" },
  gemini: { label: "Gemini", company: "Google AI Studio", href: "https://aistudio.google.com/" },
  openai: { label: "OpenAI", company: "OpenAI", href: "https://platform.openai.com/api-keys" },
  nvidia: { label: "NVIDIA NIM", company: "NVIDIA", href: "https://build.nvidia.com/" },
};

export const modelKeyLabel = (provider: string) => MODEL_KEYS[provider]?.label ?? provider;
