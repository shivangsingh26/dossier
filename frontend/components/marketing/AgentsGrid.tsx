"use client";

import { motion } from "motion/react";
import { Reveal } from "@/components/motion/Reveal";

type Agent = {
  name: string;
  blurb: string;
  tier: "lite" | "pro" | "max";
};

const AGENTS: Agent[] = [
  {
    name: "Discovery",
    blurb:
      "Pulls jobs from JSearch, Adzuna, LinkedIn, Greenhouse. Scores each against your persona before it lands in your inbox.",
    tier: "lite",
  },
  {
    name: "Watchlist",
    blurb:
      "Re-scans 70 target companies daily. Catches new roles 1–3 days before generic boards index them.",
    tier: "pro",
  },
  {
    name: "Company intel",
    blurb:
      "Tavily-powered research on each company. Tech stack, recent funding, hiring signals, eng culture — synthesized into one brief.",
    tier: "pro",
  },
  {
    name: "Gap analysis",
    blurb:
      "Counts skills you keep missing across rejected JDs. Tells you what to learn next — backed by frequency data, not vibes.",
    tier: "pro",
  },
  {
    name: "Resume tailor",
    blurb:
      "LaTeX + PDF, ATS-aware. Three-pass rewrite of bullets to match each JD's keywords without lying.",
    tier: "max",
  },
  {
    name: "Referral finder",
    blurb:
      "Surfaces people at the company you can actually reach. Drafts the cold message in your voice.",
    tier: "max",
  },
  {
    name: "Market intel",
    blurb:
      "Funding news + product launches. Spots AI/ML startups before the role is posted — apply when the hiring is hottest.",
    tier: "max",
  },
];

const TIER_STYLE: Record<Agent["tier"], string> = {
  lite: "bg-secondary/15 text-secondary",
  pro: "bg-secondary/15 text-secondary",
  max: "bg-primary/15 text-primary",
};

export function AgentsGrid() {
  return (
    <section className="border-t border-[color:var(--color-border-2)]/30 bg-[color:var(--color-surface-2)]/40">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
        <Reveal className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)] sm:text-4xl">
            Seven agents. <span className="text-primary">One pipeline.</span>
          </h2>
          <p className="mt-3 text-base text-[color:var(--color-text-muted)]">
            Each agent does one job well. Together they replace the 4-hour weekend
            job-search ritual with a 30-second morning review.
          </p>
        </Reveal>

        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {AGENTS.map((agent, i) => (
            <Reveal key={agent.name} delay={(i % 3) * 0.08 + Math.floor(i / 3) * 0.15}>
              <motion.div
                whileHover={{ y: -3 }}
                transition={{ duration: 0.2 }}
                className="group/agent rounded-lg border border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface)] p-5 transition-colors hover:border-primary/40"
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold tracking-[-0.02em] text-[color:var(--color-text)]">
                    {agent.name}
                  </h3>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${TIER_STYLE[agent.tier]}`}
                    style={{ fontFamily: "var(--font-geist-mono)" }}
                  >
                    {agent.tier}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-[color:var(--color-text-muted)]">
                  {agent.blurb}
                </p>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
