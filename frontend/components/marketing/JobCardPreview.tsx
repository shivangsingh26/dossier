"use client";

import { motion } from "motion/react";
import { Reveal } from "@/components/motion/Reveal";
import { CountUp } from "@/components/motion/CountUp";
import { Button } from "@/components/ui/button";

type SecondaryJob = {
  score: number;
  company: string;
  title: string;
  freshness: string;
};

const SECONDARY: SecondaryJob[] = [
  { score: 9, company: "Zimmer Biomet", title: "Data Scientist", freshness: "1d ago" },
  { score: 8, company: "GetSetYo", title: "AI Engineer", freshness: "6h ago" },
  { score: 8, company: "Razorpay", title: "ML Engineer · Risk", freshness: "11h ago" },
];

export function JobCardPreview() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
      <Reveal className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)] sm:text-4xl">
          Your inbox, ranked.
        </h2>
        <p className="mt-3 text-base text-[color:var(--color-text-muted)]">
          Every job comes with a score, a why-match, and a one-click action.
          Real jobs from the run above, not screenshots.
        </p>
      </Reveal>

      <div className="mx-auto mt-12 max-w-3xl space-y-3">
        <Reveal delay={0.05}>
          <motion.article
            whileHover={{ y: -3 }}
            transition={{ duration: 0.2 }}
            className="rounded-xl border border-primary/40 bg-[color:var(--color-surface)] p-6 shadow-[var(--shadow-hover)] transition-colors hover:border-primary/60"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className="rounded bg-secondary/15 px-2 py-0.5 uppercase tracking-wider text-secondary"
                    style={{ fontFamily: "var(--font-geist-mono)" }}
                  >
                    Strong fit
                  </span>
                  <span className="text-[color:var(--color-text-subtle)]">
                    2h ago · lever
                  </span>
                </div>
                <h3 className="mt-2 text-xl font-bold tracking-[-0.02em] text-[color:var(--color-text)] sm:text-2xl">
                  Machine Learning Engineer
                </h3>
                <p className="text-sm text-[color:var(--color-text-muted)]">
                  CRED · Bengaluru · 3–6 yrs
                </p>
              </div>
              <span
                className="flex items-baseline rounded-md bg-secondary/15 px-3 py-2 text-secondary"
                aria-label="Match score 8 out of 10"
              >
                <CountUp
                  to={8}
                  duration={1.4}
                  className="text-2xl tabular-nums"
                />
                <span
                  className="ml-1 text-sm text-[color:var(--color-text-subtle)]"
                  style={{ fontFamily: "var(--font-geist-mono)" }}
                >
                  /10
                </span>
              </span>
            </div>

            <ul className="mt-4 space-y-1 text-sm text-[color:var(--color-text-muted)]">
              <li className="flex gap-2">
                <span aria-hidden className="text-secondary">✓</span>
                Python + PyTorch + production ML pipelines — matches your Bodhi Atomize work
              </li>
              <li className="flex gap-2">
                <span aria-hidden className="text-secondary">✓</span>
                Bengaluru-based IC role, no people-management
              </li>
              <li className="flex gap-2">
                <span aria-hidden className="text-secondary">✓</span>
                CTC range estimated ₹28–38L — above your floor
              </li>
              <li className="flex gap-2">
                <span aria-hidden className="text-[color:var(--color-warning)]">!</span>
                Risk-modeling experience not on your CV — gap noted, easy to address
              </li>
            </ul>

            <div className="mt-5 flex flex-wrap gap-2">
              <Button size="sm">Tailor resume — 12 cr</Button>
              <Button size="sm" variant="outline">
                Find referral — 6 cr
              </Button>
              <Button size="sm" variant="ghost">
                Open JD →
              </Button>
            </div>
          </motion.article>
        </Reveal>

        <Reveal delay={0.15}>
          <div className="rounded-xl border border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface)]/60 px-2 py-2">
            {SECONDARY.map((job) => (
              <motion.div
                key={`${job.company}-${job.title}`}
                whileHover={{ x: 3 }}
                transition={{ duration: 0.18 }}
                className="flex items-center justify-between gap-3 rounded-md px-3 py-2.5 text-sm transition-colors hover:bg-[color:var(--color-surface)]"
              >
                <div className="flex items-center gap-3 truncate">
                  <span
                    className="rounded bg-secondary/15 px-1.5 py-0.5 text-secondary tabular-nums"
                    style={{ fontFamily: "var(--font-geist-mono)" }}
                  >
                    {job.score}
                  </span>
                  <span className="truncate text-[color:var(--color-text)]">
                    {job.company} · {job.title}
                  </span>
                </div>
                <span className="shrink-0 text-xs text-[color:var(--color-text-subtle)]">
                  {job.freshness}
                </span>
              </motion.div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
