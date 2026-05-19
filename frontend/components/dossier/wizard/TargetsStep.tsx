"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { TargetsSchema, type TargetsForm, type TargetsFormParsed } from "@/lib/persona-schema";
import { usePersonaApi } from "@/lib/api/persona";

const inputCls = "w-full rounded-md border border-[color:var(--color-border-2)] bg-[color:var(--color-surface-2)] px-3 py-2 text-sm text-[color:var(--color-text)] focus:border-primary focus:outline-none";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm text-[color:var(--color-text)] mb-1.5">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-[color:var(--color-danger)]">{error}</p>}
    </div>
  );
}

export function TargetsStep({
  onComplete,
}: {
  onComplete: () => void;
}) {
  const api = usePersonaApi();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<TargetsForm, unknown, TargetsFormParsed>({
    resolver: zodResolver(TargetsSchema),
    defaultValues: {
      identity: { name: "", current_role: "", current_company: "", months_experience: 0, current_ctc_lpa: 0, github_username: "" },
      target: { min_salary_lpa: 25, preferred_salary_lpa: 30, roles: [], locations: [], company_tiers: [], hard_nos: [] },
      work_preferences: { work_style: "hybrid", open_to_relocation: false, relocation_cities: [] },
    },
  });

  async function onSubmit(data: TargetsFormParsed) {
    setBusy(true); setError(null);
    try {
      await api.saveQuestionnaire(data);
      onComplete();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
      <div>
        <h2 className="font-display text-xl font-semibold text-[color:var(--color-text)]">Job targets</h2>
        <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
          Tell us what you&apos;re looking for. We use this for every job match.
        </p>
      </div>

      <Field label="Your name" error={errors.identity?.name?.message}>
        <input {...register("identity.name")} className={inputCls} />
      </Field>

      <Field label="Current role" error={errors.identity?.current_role?.message}>
        <input {...register("identity.current_role")} placeholder="AI Engineer" className={inputCls} />
      </Field>

      <Field label="Current company">
        <input {...register("identity.current_company")} className={inputCls} />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Months of experience">
          <input type="number" {...register("identity.months_experience")} className={inputCls} />
        </Field>
        <Field label="Current CTC (LPA)">
          <input type="number" step="0.5" {...register("identity.current_ctc_lpa")} className={inputCls} />
        </Field>
      </div>

      <Field label="GitHub username (optional)">
        <input {...register("identity.github_username")} className={inputCls} />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Min salary (LPA)" error={errors.target?.min_salary_lpa?.message}>
          <input type="number" {...register("target.min_salary_lpa")} className={inputCls} />
        </Field>
        <Field label="Preferred salary (LPA)">
          <input type="number" {...register("target.preferred_salary_lpa")} className={inputCls} />
        </Field>
      </div>

      <Field label="Target roles (comma-separated)" error={errors.target?.roles?.message}>
        <input
          {...register("target.roles", {
            setValueAs: (v: string) => (typeof v === "string" ? v.split(",").map(s => s.trim()).filter(Boolean) : v),
          })}
          placeholder="MLE-1, AI Engineer, Applied Scientist"
          className={inputCls}
        />
      </Field>

      <Field label="Locations (comma-separated)" error={errors.target?.locations?.message}>
        <input
          {...register("target.locations", {
            setValueAs: (v: string) => (typeof v === "string" ? v.split(",").map(s => s.trim()).filter(Boolean) : v),
          })}
          placeholder="Bengaluru, Remote"
          className={inputCls}
        />
      </Field>

      <Field label="Hard nos (comma-separated)">
        <input
          {...register("target.hard_nos", {
            setValueAs: (v: string) => (typeof v === "string" ? v.split(",").map(s => s.trim()).filter(Boolean) : v),
          })}
          placeholder="service_company, no_ml_in_prod"
          className={inputCls}
        />
      </Field>

      <Field label="Work style">
        <select {...register("work_preferences.work_style")} className={inputCls}>
          <option value="hybrid">Hybrid</option>
          <option value="remote">Remote-only</option>
          <option value="onsite">On-site</option>
        </select>
      </Field>

      <label className="flex items-center gap-2 text-sm text-[color:var(--color-text)]">
        <input type="checkbox" {...register("work_preferences.open_to_relocation")} />
        Open to relocation
      </label>

      {error && <p className="text-sm text-[color:var(--color-danger)]">{error}</p>}

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-[color:var(--color-bg)] disabled:opacity-40"
      >
        {busy ? "Saving..." : "Save & continue"}
      </button>
    </form>
  );
}
