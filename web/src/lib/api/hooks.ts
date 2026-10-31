"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, postJson } from "./client";
import type { ModelKeyCheck, SavedModelKey } from "./model-key";
import type { Session } from "./session";
import type {
  AskRequest,
  AskResponse,
  Checkpoint,
  ForkRequest,
  Health,
  IncidentOut,
  ProviderOut,
  ReviewRequest,
  RunAccepted,
  RunDetail,
  RunPage,
  RunState,
  RunStatus,
  RunbookOut,
  SampleRunRequest,
  Scenario,
  TriageRequest,
} from "./types";
import type { components } from "./schema";

export type SettingsView = components["schemas"]["SettingsOut"];
export type FeedbackView = components["schemas"]["FeedbackOut"];
export type RealIncident = components["schemas"]["RealIncidentOut"];
export type ReplayRequest = components["schemas"]["ReplayRequest"];
export type ExpertCheck = components["schemas"]["ExpertCheckOut"];

export const keys = {
  session: ["session"] as const,
  modelKey: ["model-key"] as const,
  health: ["health"] as const,
  runs: (status?: RunStatus | "all", limit?: number) =>
    ["runs", status ?? "all", limit ?? 50] as const,
  run: (id: string) => ["run", id] as const,
  state: (id: string, checkpoint?: string | null) =>
    ["run", id, "state", checkpoint ?? "head"] as const,
  history: (id: string) => ["run", id, "history"] as const,
  incidents: ["incidents"] as const,
  incident: (id: string) => ["incidents", id] as const,
  runbooks: ["runbooks"] as const,
  runbook: (slug: string) => ["runbooks", slug] as const,
  providers: ["providers"] as const,
  settings: ["settings"] as const,
  feedback: ["feedback"] as const,
  realIncidents: ["real-incidents"] as const,
  scenarios: ["scenarios"] as const,
};

const v1 = (path: string) => `/api/v1${path}`;
const runPath = (id: string, rest = "") => v1(`/runs/${encodeURIComponent(id)}${rest}`);

export function useSession() {
  return useQuery({
    queryKey: keys.session,
    queryFn: () => apiFetch<Session>("/api/session"),
    staleTime: 60_000,
    // While the API is asleep, starting or busy, ask again every few seconds, so an open tab
    // carries on by itself once it answers.
    refetchInterval: (query) => {
      const session = query.state.data;
      const waiting =
        query.state.status === "error" ||
        (session !== undefined && (!session.reachable || session.busy === true));
      return waiting ? 5_000 : false;
    },
  });
}

export function useSignIn() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => postJson<Session>("/api/session", { key }),
    onSuccess: async (session) => {
      client.setQueryData(keys.session, session);
      await client.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "session" });
    },
  });
}

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/api/session", { method: "DELETE" }),
    onSuccess: () => {
      client.clear();
    },
  });
}

/** The visitor's own model key, if they saved one: its provider and last four characters. */
export function useModelKey() {
  return useQuery({
    queryKey: keys.modelKey,
    queryFn: () => apiFetch<SavedModelKey>("/api/model-key"),
    staleTime: 60_000,
  });
}

/** Check a key with its provider through the ARIA API, and keep it only if it is accepted. */
export function useSaveModelKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider: string; key: string }) =>
      postJson<ModelKeyCheck>("/api/model-key", body),
    onSuccess: async (result) => {
      if (result.accepted) await client.invalidateQueries({ queryKey: keys.modelKey });
    },
  });
}

export function useForgetModelKey() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>("/api/model-key", { method: "DELETE" }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: keys.modelKey });
    },
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => apiFetch<Health>("/api/ready"),
    // Every half minute; every five seconds while the server is not answering.
    refetchInterval: (query) => (query.state.status === "error" ? 5_000 : 30_000),
  });
}

/** Incidents, newest first, checked again every ``every`` ms (a count in the menu can wait longer
 * than a list someone is reading). */
export function useRuns(status: RunStatus | "all" = "all", limit = 50, every = 10_000) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (status !== "all") query.set("status", status);
  return useQuery({
    queryKey: keys.runs(status, limit),
    queryFn: () => apiFetch<RunPage>(v1(`/runs?${query.toString()}`)),
    refetchInterval: every,
    placeholderData: keepPreviousData,
  });
}

const ACTIVE: ReadonlySet<string> = new Set(["queued", "running"]);

export function useRun(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.run(id),
    queryFn: () => apiFetch<RunDetail>(runPath(id)),
    enabled,
    refetchInterval: (query) => (ACTIVE.has(query.state.data?.status ?? "") ? 4_000 : false),
  });
}

export function useRunState(id: string, checkpoint?: string | null, enabled = true) {
  const search = checkpoint ? `?checkpoint_id=${encodeURIComponent(checkpoint)}` : "";
  return useQuery({
    queryKey: keys.state(id, checkpoint),
    queryFn: () => apiFetch<RunState>(runPath(id, `/state${search}`)),
    enabled,
    placeholderData: checkpoint ? keepPreviousData : undefined,
  });
}

export function useHistory(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.history(id),
    queryFn: () => apiFetch<Checkpoint[]>(runPath(id, "/history?limit=200")),
    enabled,
  });
}

export function useIncidents(query?: string, system?: string) {
  const params = new URLSearchParams({ limit: query ? "20" : "100" });
  if (query) params.set("q", query);
  if (system) params.set("system", system);
  return useQuery({
    queryKey: [...keys.incidents, query ?? "", system ?? ""],
    queryFn: () => apiFetch<IncidentOut[]>(v1(`/incidents?${params.toString()}`)),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useRunbooks() {
  return useQuery({
    queryKey: keys.runbooks,
    queryFn: () => apiFetch<RunbookOut[]>(v1("/runbooks")),
    staleTime: 5 * 60_000,
  });
}

export function useRunbook(slug: string) {
  return useQuery({
    queryKey: keys.runbook(slug),
    queryFn: () => apiFetch<RunbookOut>(v1(`/runbooks/${encodeURIComponent(slug)}`)),
    staleTime: 5 * 60_000,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: () => apiFetch<ProviderOut[]>(v1("/providers")),
    refetchInterval: 30_000,
  });
}

export function useSettingsView() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => apiFetch<SettingsView>(v1("/settings")),
    staleTime: 60_000,
  });
}

export function useFeedback(limit = 8) {
  return useQuery({
    queryKey: [...keys.feedback, limit],
    queryFn: () => apiFetch<FeedbackView>(v1(`/feedback?limit=${limit}`)),
    staleTime: 30_000,
  });
}

/** The samples this server can build, by where their logs come from. */
export function useScenarios() {
  return useQuery({
    queryKey: keys.scenarios,
    queryFn: () => apiFetch<Scenario[]>(v1("/scenarios")),
    staleTime: 10 * 60_000,
  });
}

/** Build a sample on the server, at a size it offers, and start its triage. */
export function useStartSample() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: SampleRunRequest }) =>
      postJson<RunAccepted>(v1(`/scenarios/${encodeURIComponent(id)}/runs`), body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useRealIncidents() {
  return useQuery({
    queryKey: keys.realIncidents,
    queryFn: () => apiFetch<RealIncident[]>(v1("/real-incidents")),
    staleTime: 5 * 60_000,
  });
}

/** A replayed real incident's flagged units next to the experts' labels; polls until parsed. */
export function useExpertCheck(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["run", id, "expert-check"] as const,
    queryFn: () => apiFetch<ExpertCheck>(runPath(id, "/expert-check")),
    enabled,
    refetchInterval: (query) => (query.state.data?.ready ? false : 2_000),
  });
}

// --- writes ------------------------------------------------------------------------------------

export function useCreateRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (request: TriageRequest) => postJson<RunAccepted>(v1("/runs"), request),
    onSuccess: () => client.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useReplay() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ReplayRequest }) =>
      postJson<RunAccepted>(v1(`/real-incidents/${encodeURIComponent(id)}/replay`), body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useReview(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewRequest) => postJson<RunDetail>(runPath(id, "/review"), body),
    onSuccess: async (detail) => {
      client.setQueryData(keys.run(id), detail);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["run", id] }),
        client.invalidateQueries({ queryKey: ["runs"] }),
      ]);
    },
  });
}

export function useResend(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (actionId: string) =>
      postJson<RunDetail>(runPath(id, `/actions/${encodeURIComponent(actionId)}/resend`), {}),
    onSuccess: async (detail) => {
      client.setQueryData(keys.run(id), detail);
      await client.invalidateQueries({ queryKey: ["run", id] });
    },
  });
}

export function useFork(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ForkRequest) => postJson<RunAccepted>(runPath(id, "/fork"), body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useDeleteRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(runPath(id), { method: "DELETE" }),
    onSuccess: async (_, id) => {
      client.removeQueries({ queryKey: ["run", id] });
      await client.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useAsk() {
  return useMutation({
    mutationFn: (body: AskRequest) => postJson<AskResponse>(v1("/ask"), body),
  });
}
