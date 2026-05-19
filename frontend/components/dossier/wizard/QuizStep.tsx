"use client";

import { useEffect, useRef, useState } from "react";
import { usePersonaApi } from "@/lib/api/persona";
import type { QuizQuestion } from "@/lib/persona-schema";

type Msg = { role: "bot" | "user"; text: string; hint?: string };

export function QuizStep({ onComplete }: { onComplete: () => void }) {
  const api = usePersonaApi();
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [idx, setIdx] = useState(0);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.getQuizQuestions().then((qs) => {
      setQuestions(qs);
      if (qs[0]) {
        setMsgs([{ role: "bot", text: qs[0].question, hint: qs[0].hint }]);
      }
    }).catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitAnswer() {
    if (!input.trim()) return;
    const answer = input.trim();
    setInput("");
    setMsgs((m) => [...m, { role: "user", text: answer }]);

    const nextIdx = idx + 1;
    if (nextIdx >= questions.length) {
      const allAnswers: Record<string, string> = {};
      const userBubbles = [...msgs, { role: "user" as const, text: answer }].filter(m => m.role === "user");
      userBubbles.forEach((m, i) => {
        if (questions[i]) allAnswers[questions[i].id] = m.text;
      });
      setBusy(true);
      try {
        await api.saveQuizAnswers(allAnswers);
        onComplete();
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
      return;
    }

    setIdx(nextIdx);
    setMsgs((m) => [...m, { role: "bot", text: questions[nextIdx].question, hint: questions[nextIdx].hint }]);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">
          Quick interview — {questions.length ? `question ${Math.min(idx + 1, questions.length)} of ${questions.length}` : "loading..."}
        </h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          Be specific. Specific answers produce better job matches.
        </p>
      </div>

      <div className="max-h-[50vh] overflow-y-auto space-y-3 pr-2">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={
              m.role === "bot"
                ? "max-w-[85%] rounded-2xl rounded-tl-sm bg-[color:var(--color-surface-2)] border border-[color:var(--color-border-2)] px-4 py-3 text-sm text-[color:var(--color-text)] whitespace-pre-wrap"
                : "ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-primary/15 border border-primary/30 px-4 py-3 text-sm text-[color:var(--color-text)] whitespace-pre-wrap"
            }
          >
            {m.text}
            {m.role === "bot" && m.hint && (
              <div className="mt-2 text-xs text-[color:var(--color-text-subtle)] whitespace-pre-wrap">
                {m.hint}
              </div>
            )}
          </div>
        ))}
      </div>

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      {idx < questions.length && (
        <div className="space-y-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submitAnswer();
              }
            }}
            rows={3}
            placeholder="Type your answer... (Cmd/Ctrl + Enter to send)"
            className="w-full resize-y rounded-md border border-[color:var(--color-border-2)] bg-[color:var(--color-surface-2)] px-3 py-2 text-sm text-[color:var(--color-text)] focus:border-primary focus:outline-none"
          />
          <button
            onClick={submitAnswer}
            disabled={busy || !input.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
          >
            {idx === questions.length - 1 ? (busy ? "Saving..." : "Send & finish") : "Send"}
          </button>
        </div>
      )}
    </div>
  );
}
