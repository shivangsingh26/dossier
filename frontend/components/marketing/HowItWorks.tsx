"use client";

import { motion } from "motion/react";
import { Reveal } from "@/components/motion/Reveal";

type Step = {
  index: number;
  title: string;
  body: string;
};

const STEPS: Step[] = [
  {
    index: 1,
    title: "Build your persona",
    body: "Upload your resume + LinkedIn. Answer 12 quick questions in a chat. Dossier learns what role fits, what salary floor, what locations work, what you actually care about.",
  },
  {
    index: 2,
    title: "Run the agents",
    body: "One click. Seven agents fan out — discovery, watchlist, intel, gap, resume, referral, market. Every job is scored against your persona before you see it.",
  },
  {
    index: 3,
    title: "Review and act",
    body: "Open your inbox. See ranked jobs with score, why-match, draft tailored resume, suggested referral contact, draft cold message. You approve. You send.",
  },
];

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20"
    >
      <Reveal className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)] sm:text-4xl">
          How it works.
        </h2>
        <p className="mt-3 text-base text-[color:var(--color-text-muted)]">
          Three steps. About five minutes to set up. Then it runs every morning.
        </p>
      </Reveal>

      <ol className="mt-14 grid gap-6 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <Reveal key={step.index} delay={i * 0.1}>
            <motion.li
              whileHover={{ y: -4 }}
              transition={{ duration: 0.2 }}
              className="relative rounded-xl border border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface)] p-6 transition-colors hover:border-primary/40"
            >
              <span
                className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-primary/15 text-base text-primary"
                style={{ fontFamily: "var(--font-geist-mono)" }}
                aria-hidden
              >
                0{step.index}
              </span>
              <h3 className="mt-5 text-xl font-bold tracking-[-0.02em] text-[color:var(--color-text)]">
                {step.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-[color:var(--color-text-muted)]">
                {step.body}
              </p>
            </motion.li>
          </Reveal>
        ))}
      </ol>
    </section>
  );
}
