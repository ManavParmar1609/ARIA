/** What the console knows about the caller (GET /api/session on this server). */
export interface Session {
  /** The API requires a key (ARIA_API_KEYS is set). */
  authRequired: boolean;
  signedIn: boolean;
  /** The key's name, used as the reviewer's name on decisions. */
  name: string | null;
  /** False when this server could not reach the ARIA API at all. */
  reachable: boolean;
  /** True when the API answered but turned the request away for now (too many at once). */
  busy?: boolean;
}
