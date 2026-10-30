"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { AguiChat } from "@/components/console/agui-chat";
import { PageHeader } from "@/components/console/states";
import { Citations, EvidencePanel, EvidenceProvider } from "@/components/run/evidence";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/client";
import { useAsk, useRuns } from "@/lib/api/hooks";
import type { AskResponse } from "@/lib/api/types";
import { stripSeverity } from "@/lib/format";

const SUGGESTIONS = [
  "Have we seen ZooKeeper lose quorum before, and how was it fixed?",
  "What does the runbook say to do first when DataNodes fail to serve blocks?",
  "Which past incidents involved SSH brute-force attempts on many hosts?",
];

interface Turn {
  id: string;
  question: string;
  runId: string | null;
  answer?: AskResponse;
  error?: string;
}

function Answer({ turn }: { turn: Turn }) {
  const answer = turn.answer;
  if (turn.error) {
    return (
      <p role="alert" className="text-sm text-danger">
        {turn.error}
      </p>
    );
  }
  if (!answer) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <span aria-hidden className="block size-2 animate-pulse-dot rounded-full bg-primary" />
        Searching incident memory and runbooks
      </p>
    );
  }
  return (
    <EvidenceProvider evidence={answer.evidence} events={[]}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="grid content-start gap-3">
          {answer.insufficient_evidence ? (
            <p className="rounded-md bg-sev3/12 p-3 text-sm">
              ARIA did not find enough evidence to answer that confidently. What it found is below.
            </p>
          ) : null}
          <ul className="grid gap-2.5">
            {answer.answer.map((claim, i) => (
              <li key={i} className="leading-relaxed">
                {claim.text} <Citations ids={claim.evidence_ids ?? []} />
              </li>
            ))}
          </ul>
          <p className="text-xs text-faint">
            {answer.answered_by === "llm"
              ? `Written by ${answer.model ?? "the LLM"} from the evidence.`
              : "Assembled from retrieved evidence, without an LLM."}
          </p>
        </div>
        <EvidencePanel className="self-start" />
      </div>
    </EvidenceProvider>
  );
}

function Questions() {
  const id = useId();
  const ask = useAsk();
  const runs = useRuns("all", 30);
  const [question, setQuestion] = useState("");
  const [runId, setRunId] = useState<string>("none");
  const [turns, setTurns] = useState<Turn[]>([]);
  const counter = useRef(0);

  const send = (text: string) => {
    const q = text.trim();
    if (q.length < 3 || ask.isPending) return;
    counter.current += 1;
    const turn: Turn = {
      id: `q${counter.current}`,
      question: q,
      runId: runId === "none" ? null : runId,
    };
    setTurns((list) => [turn, ...list]);
    setQuestion("");
    ask.mutate(
      { question: q, run_id: turn.runId },
      {
        onSuccess: (answer) =>
          setTurns((list) => list.map((t) => (t.id === turn.id ? { ...t, answer } : t))),
        onError: (error) =>
          setTurns((list) =>
            list.map((t) =>
              t.id === turn.id
                ? { ...t, error: error instanceof ApiError ? error.detail : error.message }
                : t,
            ),
          ),
      },
    );
  };

  return (
    <div className="grid gap-8">
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          send(question);
        }}
        className="grid gap-3"
      >
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-[minmax(0,1fr)_16rem]">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-q`}>Your question</Label>
            <Input
              id={`${id}-q`}
              value={question}
              maxLength={1000}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="What happened last time HDFS DataNodes failed to serve blocks?"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-run`}>About a run</Label>
            <Select value={runId} onValueChange={setRunId}>
              <SelectTrigger id={`${id}-run`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Any incident</SelectItem>
                {(runs.data?.runs ?? []).map((run) => (
                  <SelectItem key={run.id} value={run.id}>
                    {stripSeverity(run.title) || run.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button
            type="submit"
            variant="primary"
            disabled={question.trim().length < 3 || ask.isPending}
          >
            Ask ARIA
          </Button>
          <p className="text-sm text-muted-foreground">
            Answers come only from incident memory, runbooks and the chosen run&apos;s evidence, and
            every statement cites what it rests on.
          </p>
        </div>
      </form>

      {turns.length === 0 ? (
        <section aria-labelledby={`${id}-try`} className="grid gap-2">
          <h2 id={`${id}-try`} className="font-sans text-sm font-semibold">
            Not sure what to ask? Try one of these
          </h2>
          <ul className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <li key={s} className="min-w-0">
                <Button
                  size="sm"
                  variant="secondary"
                  // Questions are long: let them wrap on a phone rather than widen the page.
                  className="h-auto min-h-9 py-1.5 text-left whitespace-normal"
                  onClick={() => send(s)}
                >
                  {s}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <ol className="grid gap-8">
          {turns.map((turn) => (
            <li key={turn.id} className="grid gap-3 border-t border-rule pt-6">
              <h2 className="text-xl tracking-heading wrap-anywhere">{turn.question}</h2>
              <Answer turn={turn} />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function Ask() {
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Ask ARIA"
        description="Ask about past incidents and runbooks, or triage logs in a chat."
      />
      <Tabs defaultValue="ask">
        <TabsList aria-label="Ask ARIA modes">
          <TabsTrigger value="ask">Ask about incidents</TabsTrigger>
          <TabsTrigger value="chat">Triage in chat</TabsTrigger>
        </TabsList>
        <TabsContent value="ask">
          <Questions />
        </TabsContent>
        <TabsContent value="chat">
          <AguiChat />
        </TabsContent>
      </Tabs>
    </div>
  );
}
