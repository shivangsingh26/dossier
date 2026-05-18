import Link from "next/link";
import { Lockup } from "@/components/brand/Lockup";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-[color:var(--color-bg)] px-4 py-12">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 mx-auto h-[320px] w-[640px] rounded-full opacity-15 blur-[120px]"
        style={{ background: "#f97316" }}
      />
      <Link href="/" className="relative mb-8" aria-label="Dossier home">
        <Lockup size="md" />
      </Link>
      <div className="relative">{children}</div>
    </div>
  );
}
