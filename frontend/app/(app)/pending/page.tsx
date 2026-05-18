import { SignOutButton } from "@clerk/nextjs";

export default function PendingReviewPage() {
  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center px-6 text-center">
      <h1 className="font-display text-3xl font-semibold text-[color:var(--color-text)]">
        Your account is pending review.
      </h1>
      <p className="mt-4 max-w-md text-[color:var(--color-text-muted)]">
        Dossier is in closed beta. An admin will approve your account shortly —
        you&apos;ll get an email when you&apos;re in.
      </p>
      <div className="mt-8">
        <SignOutButton>
          <button className="rounded-md border border-[color:var(--color-border-2)] px-4 py-2 text-sm text-[color:var(--color-text)] hover:bg-[color:var(--color-surface)]">
            Sign out
          </button>
        </SignOutButton>
      </div>
    </div>
  );
}
