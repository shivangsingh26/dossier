import { currentUser } from "@clerk/nextjs/server";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { fetchMe } from "@/lib/server-api";

const TIER_LABEL = { lite: "Lite", pro: "Pro", max: "Max" } as const;
const TIER_TAGLINE = {
  lite: "free forever",
  pro: "₹999 intent",
  max: "₹2,999 intent",
} as const;

export default async function DashboardPage() {
  const user = await currentUser();
  const name = user?.firstName ?? "there";

  // Layout already gated on active status — me is guaranteed kind=ok here,
  // but we re-fetch (cached at RSC level) to keep this component self-contained.
  const me = await fetchMe();
  const credits = me.kind === "ok" ? me.account.credits : 0;
  const tier = me.kind === "ok" ? me.account.tier : "lite";

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-3xl font-extrabold tracking-[-0.035em] text-[color:var(--color-text)] sm:text-4xl">
        Welcome, <span className="text-primary">{name}</span>.
      </h1>
      <p className="mt-3 text-[color:var(--color-text-muted)]">
        Your inbox is empty. Set up your persona to start surfacing jobs.
      </p>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-[color:var(--color-text)]">Next step</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-[color:var(--color-text-muted)]">
              Onboarding (persona builder) ships in M3.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-[color:var(--color-text)]">Credits</CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className="text-3xl text-primary tabular-nums"
              style={{ fontFamily: "var(--font-geist-mono)" }}
            >
              {credits.toLocaleString()}
            </p>
            <p className="mt-1 text-xs text-[color:var(--color-text-subtle)]">
              remaining this period
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-[color:var(--color-text)]">Tier</CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className="text-3xl text-secondary"
              style={{ fontFamily: "var(--font-geist-mono)" }}
            >
              {TIER_LABEL[tier]}
            </p>
            <p className="mt-1 text-xs text-[color:var(--color-text-subtle)]">
              {TIER_TAGLINE[tier]}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
