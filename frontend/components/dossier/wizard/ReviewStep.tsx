"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { usePersonaApi } from "@/lib/api/persona";
import { SynthesisProgress } from "./SynthesisProgress";

type Mode = "kicking-off" | "synthesizing" | "review" | "saving" | "error";

export function ReviewStep() {
  const api = usePersonaApi();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("kicking-off");
  const [runId, setRunId] = useState<string | null>(null);
  const [, setPersona] = useState<Record<string, unknown> | null>(null);
  const [edited, setEdited] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.finalize().then((r) => {
      setRunId(r.run_id);
      setMode("synthesizing");
    }).catch((e) => {
      setError((e as Error).message);
      setMode("error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadPersona() {
    const p = await api.getPersona();
    if (p) {
      setPersona(p);
      setEdited(JSON.stringify(p, null, 2));
    }
    setMode("review");
  }

  async function saveEdits() {
    setMode("saving");
    try {
      const parsed = JSON.parse(edited);
      await api.patchPersona(parsed);
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
      setMode("review");
    }
  }

  if (mode === "kicking-off") {
    return <p className="text-[color:var(--color-text-muted)]">Starting synthesis...</p>;
  }

  if (mode === "synthesizing" && runId) {
    return (
      <SynthesisProgress
        runId={runId}
        onComplete={loadPersona}
        onFailed={(msg) => {
          setError(msg);
          setMode("error");
        }}
      />
    );
  }

  if (mode === "error") {
    return (
      <div className="space-y-3">
        <h2 className="font-display text-xl text-[color:var(--color-danger)]">Synthesis failed</h2>
        <p className="text-sm text-[color:var(--color-text-muted)]">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)]"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">
          Review your persona
        </h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          Edit any field directly in the JSON below. Click &quot;Looks good&quot; to save and start matching jobs.
        </p>
      </div>

      <textarea
        value={edited}
        onChange={(e) => setEdited(e.target.value)}
        rows={20}
        className="w-full rounded-md border border-[color:var(--color-border-2)] bg-[color:var(--color-surface-2)] px-3 py-2 font-mono text-xs text-[color:var(--color-text)] focus:border-primary focus:outline-none"
      />

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      <button
        onClick={saveEdits}
        disabled={mode === "saving"}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
      >
        {mode === "saving" ? "Saving..." : "Looks good — start matching jobs"}
      </button>
    </div>
  );
}
