"use client";

import { useState } from "react";
import { Stepper } from "@/components/dossier/wizard/Stepper";
import { UploadStep } from "@/components/dossier/wizard/UploadStep";
import { TargetsStep } from "@/components/dossier/wizard/TargetsStep";
import { QuizStep } from "@/components/dossier/wizard/QuizStep";
import { ReviewStep } from "@/components/dossier/wizard/ReviewStep";

const STEPS = [
  { id: "upload", label: "Upload" },
  { id: "targets", label: "Targets" },
  { id: "quiz", label: "Quiz" },
  { id: "review", label: "Review" },
];

export default function OnboardingPage() {
  const [current, setCurrent] = useState(0);

  return (
    <div className="mx-auto max-w-3xl py-10">
      <h1 className="font-display text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)]">
        Set up your persona
      </h1>
      <p className="mt-2 text-[color:var(--color-text-muted)]">
        4 quick steps. Takes about 10 minutes. Everything is saved as you go.
      </p>

      <div className="mt-8">
        <Stepper steps={STEPS} current={current} />
      </div>

      <div className="mt-10 rounded-xl border border-[color:var(--color-border-2)]/60 bg-[color:var(--color-surface)] p-8">
        {current === 0 && <UploadStep onComplete={() => setCurrent(1)} />}
        {current === 1 && <TargetsStep onComplete={() => setCurrent(2)} />}
        {current === 2 && <QuizStep onComplete={() => setCurrent(3)} />}
        {current === 3 && <ReviewStep />}
      </div>

      <div className="mt-6 flex justify-between">
        <button
          onClick={() => setCurrent((c) => Math.max(0, c - 1))}
          disabled={current === 0}
          className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)] disabled:opacity-40"
        >
          Back
        </button>
      </div>
    </div>
  );
}
