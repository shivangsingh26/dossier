import { auth } from "@clerk/nextjs/server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Sidebar } from "@/components/dossier/Sidebar";
import { CreditPill } from "@/components/dossier/CreditPill";
import { fetchMe, fetchPersonaState } from "@/lib/server-api";
import PendingReviewPage from "./pending/page";

const CREDITS_BY_TIER = { lite: 50, pro: 500, max: 2000 } as const;

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  const me = await fetchMe();

  // Webhook hasn't provisioned the row yet (race after fresh signup), or admin
  // hasn't approved. Either way, render pending — it's the safe degenerate state.
  if (me.kind === "no-account") {
    return (
      <div className="flex min-h-screen bg-[color:var(--color-bg)]">
        <main className="flex-1">
          <PendingReviewPage />
        </main>
      </div>
    );
  }

  if (me.kind === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[color:var(--color-bg)] px-6">
        <div className="max-w-md text-center text-[color:var(--color-text)]">
          <h1 className="font-display text-2xl">Backend unreachable</h1>
          <p className="mt-3 text-sm text-[color:var(--color-text-muted)]">
            Could not reach the API ({me.status}). Is uvicorn running on{" "}
            <code>:8000</code>?
          </p>
        </div>
      </div>
    );
  }

  const account = me.account;

  if (account.status === "pending") {
    return (
      <div className="flex min-h-screen bg-[color:var(--color-bg)]">
        <main className="flex-1">
          <PendingReviewPage />
        </main>
      </div>
    );
  }

  if (account.status === "suspended") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[color:var(--color-bg)] text-[color:var(--color-text)]">
        Account suspended.
      </div>
    );
  }

  const pathname = (await headers()).get("x-pathname") ?? "";
  const onOnboarding = pathname.startsWith("/onboarding");
  if (!onOnboarding) {
    const personaState = await fetchPersonaState();
    if (personaState && !personaState.synthesized) {
      redirect("/onboarding");
    }
  }

  const creditsTotal = CREDITS_BY_TIER[account.tier];

  return (
    <div className="flex min-h-screen bg-[color:var(--color-bg)]">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-end gap-3 border-b border-[color:var(--color-border-2)]/40 bg-[color:var(--color-bg)]/80 px-4 backdrop-blur sm:px-6">
          <CreditPill credits={account.credits} creditsTotal={creditsTotal} />
        </header>
        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-10">{children}</main>
      </div>
    </div>
  );
}
