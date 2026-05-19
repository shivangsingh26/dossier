"use client";

import { useEffect, useState } from "react";
import { usePersonaApi, type PipelineRun } from "@/lib/api/persona";

export function SynthesisProgress({
  runId,
  onComplete,
  onFailed,
}: {
  runId: string;
  onComplete: () => void;
  onFailed: (msg: string) => void;
}) {
  const api = usePersonaApi();
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const start = Date.now();

    async function tick() {
      try {
        const r = await api.getRun(runId);
        if (cancelled) return;
        setRun(r);
        setElapsed(Math.floor((Date.now() - start) / 1000));
        if (r.status === "completed") {
          onComplete();
          return;
        }
        if (r.status === "failed") {
          onFailed(r.error || "synthesis failed");
          return;
        }
        setTimeout(tick, 2000);
      } catch (e) {
        if (!cancelled) onFailed((e as Error).message);
      }
    }
    tick();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  return (
    <div className="space-y-4 text-center py-10">
      <div className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-[color:var(--color-border-2)] border-t-primary" />
      <h2 className="font-display text-xl text-[color:var(--color-text)]">
        Synthesizing your persona
      </h2>
      <p className="text-sm text-[color:var(--color-text-muted)]">
        {run?.status === "queued" && "Queued — worker will pick this up shortly..."}
        {run?.status === "running" && `Running — typically takes 30-60 seconds. (${elapsed}s elapsed)`}
      </p>
    </div>
  );
}
