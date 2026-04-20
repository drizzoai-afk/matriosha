import { auth } from "@clerk/nextjs/server";
import { LandingNavigation } from "@/components/landing/navigation";
import { HeroSection } from "@/components/landing/hero-section";
import { QuickStartTabs } from "@/components/landing/quick-start-tabs";
import { FeaturesGrid } from "@/components/landing/features-grid";
import { PricingSection } from "@/components/landing/pricing-section";
import { SiteFooter } from "@/components/landing/site-footer";

export default async function HomePage() {
  const { userId } = await auth();

  return (
    <main className="min-h-screen bg-[--bg-base] text-foreground">
      <LandingNavigation userId={userId} />
      <HeroSection userId={userId} />

      <section id="quick-start" className="mx-auto max-w-6xl px-6 py-20">
        <QuickStartTabs />
      </section>

      <section id="features" className="mx-auto max-w-6xl px-6 py-20">
        <FeaturesGrid />
      </section>

      <section id="pricing" className="mx-auto max-w-6xl px-6 py-20">
        <PricingSection userId={userId} />
      </section>

      <SiteFooter />
    </main>
  );
}
