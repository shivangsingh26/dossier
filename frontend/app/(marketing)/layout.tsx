import { MarketingNav } from "@/components/dossier/MarketingNav";
import { MarketingFooter } from "@/components/dossier/MarketingFooter";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <MarketingNav />
      <main className="flex-1">{children}</main>
      <MarketingFooter />
    </div>
  );
}
