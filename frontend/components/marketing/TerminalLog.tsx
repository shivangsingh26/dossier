"use client";

import { motion, useInView } from "motion/react";
import { useRef } from "react";
import { Reveal } from "@/components/motion/Reveal";

type Line = {
  text: string;
  kind?: "cmd" | "dim" | "ok" | "info";
};

const LINES: Line[] = [
  { text: "$ dossier run --user shivang", kind: "cmd" },
  { text: "[12:01] discovery   → fetching jobs from 4 sources", kind: "dim" },
  { text: "[12:01] discovery   → scoring 47 candidates vs persona", kind: "dim" },
  { text: "[12:02] discovery   ✓ 6 jobs ≥ 7/10  (Sarvam, CRED, Zepto…)", kind: "ok" },
  { text: "[12:02] watchlist   → scanning 71 target companies", kind: "dim" },
  { text: "[12:04] watchlist   ✓ 2 new roles at Razorpay, Atlan", kind: "ok" },
  { text: "[12:04] intel       → Tavily research on 4 companies", kind: "dim" },
  { text: "[12:05] intel       ✓ Series B · 80 ppl · hiring 12 IC roles", kind: "ok" },
  { text: "[12:05] gap         → skill-frequency vs your persona", kind: "dim" },
  { text: "[12:06] gap         ✓ 3 weak spots — Spark, dbt, Airflow", kind: "info" },
  { text: "[12:06] done — 8 jobs ready for review", kind: "ok" },
];

const COLOR_MAP: Record<NonNullable<Line["kind"]>, string> = {
  cmd: "#4ade80",
  dim: "#7a695a",
  ok: "#4ade80",
  info: "#fdba74",
};

export function TerminalLog() {
  const termRef = useRef<HTMLDivElement>(null);
  const inView = useInView(termRef, { once: true, margin: "-100px" });

  return (
    <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-20">
      <Reveal className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)] sm:text-4xl">
          Watch a run.
        </h2>
        <p className="mt-3 text-base text-[color:var(--color-text-muted)]">
          One command. Seven agents. Six minutes from cold start to ranked job inbox.
        </p>
      </Reveal>

      <Reveal delay={0.1}>
        <motion.div
          ref={termRef}
          whileHover={{ y: -2 }}
          transition={{ duration: 0.2 }}
          className="mx-auto mt-12 max-w-3xl rounded-xl border border-[color:var(--color-border-2)]/40 bg-[color:var(--color-surface-2)] p-5 shadow-[var(--shadow-card)] transition-shadow hover:shadow-[var(--shadow-hover)] sm:p-7"
        >
          <div className="mb-4 flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[color:var(--color-danger)]/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-[color:var(--color-warning)]/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-secondary/70" />
            <span className="ml-3 text-xs text-[color:var(--color-text-subtle)]">
              ~/dossier
            </span>
          </div>

          <div
            className="space-y-1 text-[13px] leading-relaxed sm:text-sm"
            style={{ fontFamily: "var(--font-geist-mono)" }}
          >
            {LINES.map((line, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -8 }}
                animate={inView ? { opacity: 1, x: 0 } : {}}
                transition={{ delay: i * 0.32, duration: 0.32, ease: "easeOut" }}
                style={{ color: COLOR_MAP[line.kind ?? "dim"] }}
              >
                {line.text}
              </motion.div>
            ))}
          </div>
        </motion.div>
      </Reveal>
    </section>
  );
}
