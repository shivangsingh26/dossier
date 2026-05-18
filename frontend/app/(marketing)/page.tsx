import { HeroSection } from "@/components/marketing/HeroSection";
import { TerminalLog } from "@/components/marketing/TerminalLog";
import { HowItWorks } from "@/components/marketing/HowItWorks";
import { AgentsGrid } from "@/components/marketing/AgentsGrid";
import { JobCardPreview } from "@/components/marketing/JobCardPreview";
import { PricingTeaser } from "@/components/marketing/PricingTeaser";
import { FinalCta } from "@/components/marketing/FinalCta";

export default function HomePage() {
  return (
    <>
      <HeroSection />
      <TerminalLog />
      <HowItWorks />
      <AgentsGrid />
      <JobCardPreview />
      <PricingTeaser />
      <FinalCta />
    </>
  );
}
