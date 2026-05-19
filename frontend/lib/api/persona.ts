// Typed client wrappers for /persona/* and /pipeline/runs/{id}.
"use client";

import { useAuth } from "@clerk/nextjs";
import type { QuizQuestion, TargetsForm } from "../persona-schema";

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

type Json = Record<string, unknown>;

export type PersonaState = {
  pdfs_uploaded: boolean;
  questionnaire_done: boolean;
  quiz_done: boolean;
  synthesized: boolean;
};

export type PipelineRun = {
  run_id: string;
  user_id: string;
  agent: string;
  status: "queued" | "running" | "completed" | "failed";
  credits_cost: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  output_summary_json: string | null;
};

export function usePersonaApi() {
  const { getToken } = useAuth();

  async function authed(path: string, init?: RequestInit): Promise<Response> {
    const token = await getToken();
    const headers = new Headers(init?.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(`${BASE}${path}`, { ...init, headers });
  }

  async function jsonPost(path: string, body: unknown): Promise<Response> {
    return authed(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  return {
    getState: async (): Promise<PersonaState> => {
      const r = await authed("/persona/state");
      if (!r.ok) throw new Error(`/persona/state ${r.status}`);
      return r.json();
    },

    uploadPdfs: async (files: { resume?: File; linkedin?: File }): Promise<void> => {
      const fd = new FormData();
      if (files.resume) fd.append("resume", files.resume);
      if (files.linkedin) fd.append("linkedin", files.linkedin);
      const r = await authed("/persona/upload-pdf", { method: "POST", body: fd });
      if (!r.ok) throw new Error(`upload-pdf ${r.status}: ${await r.text()}`);
    },

    saveQuestionnaire: async (data: TargetsForm): Promise<void> => {
      const r = await jsonPost("/persona/questionnaire", data);
      if (!r.ok) throw new Error(`questionnaire ${r.status}`);
    },

    getQuizQuestions: async (): Promise<QuizQuestion[]> => {
      const r = await authed("/persona/quiz-questions");
      if (!r.ok) throw new Error(`quiz-questions ${r.status}`);
      const body = (await r.json()) as { questions: QuizQuestion[] };
      return body.questions;
    },

    saveQuizAnswers: async (answers: Record<string, string>): Promise<void> => {
      const r = await jsonPost("/persona/quiz-answers", { answers });
      if (!r.ok) throw new Error(`quiz-answers ${r.status}`);
    },

    finalize: async (): Promise<{ run_id: string; status: string }> => {
      const r = await jsonPost("/persona/finalize", {});
      if (!r.ok) throw new Error(`finalize ${r.status}: ${await r.text()}`);
      return r.json();
    },

    getPersona: async (): Promise<Json | null> => {
      const r = await authed("/persona");
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`/persona ${r.status}`);
      return r.json();
    },

    patchPersona: async (patch: Json): Promise<Json> => {
      const r = await authed("/persona", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ patch }),
      });
      if (!r.ok) throw new Error(`patch ${r.status}`);
      return r.json();
    },

    getRun: async (runId: string): Promise<PipelineRun> => {
      const r = await authed(`/pipeline/runs/${runId}`);
      if (!r.ok) throw new Error(`run ${r.status}`);
      return r.json();
    },
  };
}
