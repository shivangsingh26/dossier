"use client";

type Step = { id: string; label: string };

export function Stepper({
  steps,
  current,
}: {
  steps: Step[];
  current: number;
}) {
  return (
    <ol className="flex items-center gap-2 text-sm">
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "active" : "todo";
        return (
          <li key={s.id} className="flex items-center gap-2">
            <span
              className={
                state === "done"
                  ? "h-7 w-7 rounded-full bg-primary text-[color:var(--color-bg)] grid place-items-center text-xs font-semibold"
                  : state === "active"
                  ? "h-7 w-7 rounded-full bg-[color:var(--color-surface)] border border-primary text-primary grid place-items-center text-xs font-semibold"
                  : "h-7 w-7 rounded-full bg-[color:var(--color-surface)] border border-[color:var(--color-border-2)] text-[color:var(--color-text-subtle)] grid place-items-center text-xs"
              }
            >
              {i + 1}
            </span>
            <span
              className={
                state === "todo"
                  ? "text-[color:var(--color-text-subtle)]"
                  : "text-[color:var(--color-text)]"
              }
            >
              {s.label}
            </span>
            {i < steps.length - 1 && (
              <span
                className={
                  state === "done"
                    ? "w-8 h-px bg-primary mx-1"
                    : "w-8 h-px bg-[color:var(--color-border-2)] mx-1"
                }
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
