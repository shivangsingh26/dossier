"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { Reveal } from "@/components/motion/Reveal";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type Tier = {
  slug: "lite" | "pro" | "max";
  name: string;
  price: string;
  priceNote: string;
  credits: string;
  features: string[];
  cta: string;
  ctaHref: string;
  highlight?: boolean;
};

const TIERS: Tier[] = [
  {
    slug: "lite",
    name: "Lite",
    price: "₹0",
    priceNote: "free forever",
    credits: "50 credits / month",
    features: [
      "Job discovery (every source)",
      "100 one-time signup credits",
      "Telegram daily digest",
      "Email support",
    ],
    cta: "Start free",
    ctaHref: "/sign-up",
  },
  {
    slug: "pro",
    name: "Pro",
    price: "₹999",
    priceNote: "per month · intent",
    credits: "500 credits / month",
    features: [
      "Everything in Lite",
      "Watchlist (70-company auto scan)",
      "Company intelligence briefs",
      "Skill gap analysis",
    ],
    cta: "Join Pro waitlist",
    ctaHref: "/sign-up?tier=pro",
    highlight: true,
  },
  {
    slug: "max",
    name: "Max",
    price: "₹2,999",
    priceNote: "per month · intent",
    credits: "2,000 credits / month",
    features: [
      "Everything in Pro",
      "Resume tailor (LaTeX + PDF)",
      "Cover letter generator",
      "Referral finder + cold message",
      "Market intel — funded startup alerts",
    ],
    cta: "Join Max waitlist",
    ctaHref: "/sign-up?tier=max",
  },
];

export default function PricingPage() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
      <Reveal className="mx-auto max-w-2xl text-center">
        <h1 className="text-4xl font-extrabold tracking-[-0.04em] text-[color:var(--color-text)] sm:text-5xl">
          Pay only when you <span className="text-primary">act.</span>
        </h1>
        <p className="mt-4 text-base text-[color:var(--color-text-muted)] sm:text-lg">
          Credits track every agent invocation. No subscriptions hide unused capacity.
        </p>
      </Reveal>

      <div className="mt-14 grid gap-6 md:grid-cols-3">
        {TIERS.map((tier, i) => (
          <Reveal key={tier.slug} delay={i * 0.1}>
            <motion.div
              whileHover={{ y: -5 }}
              transition={{ duration: 0.22 }}
            >
              <Card
                className={
                  tier.highlight
                    ? "relative border-primary shadow-[var(--shadow-hover)]"
                    : "relative transition-colors hover:border-primary/40"
                }
              >
                {tier.highlight && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-1 text-xs font-medium text-primary-foreground">
                    Most popular
                  </span>
                )}
                <CardHeader>
                  <CardTitle className="text-2xl font-bold tracking-[-0.02em]">
                    {tier.name}
                  </CardTitle>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span
                      className="text-4xl tabular-nums"
                      style={{ fontFamily: "var(--font-geist-mono)" }}
                    >
                      {tier.price}
                    </span>
                    <span className="text-sm text-[color:var(--color-text-subtle)]">
                      {tier.priceNote}
                    </span>
                  </div>
                  <p
                    className="mt-2 text-sm text-secondary"
                    style={{ fontFamily: "var(--font-geist-mono)" }}
                  >
                    {tier.credits}
                  </p>
                </CardHeader>
                <CardContent className="space-y-4">
                  <ul className="space-y-2 text-sm text-[color:var(--color-text-muted)]">
                    {tier.features.map((f) => (
                      <li key={f} className="flex gap-2">
                        <span aria-hidden className="text-secondary">
                          ✓
                        </span>
                        {f}
                      </li>
                    ))}
                  </ul>
                  <Button
                    asChild
                    variant={tier.highlight ? "default" : "secondary"}
                    className="w-full"
                  >
                    <Link href={tier.ctaHref}>{tier.cta}</Link>
                  </Button>
                </CardContent>
              </Card>
            </motion.div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
