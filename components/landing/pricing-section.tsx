import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface PricingSectionProps {
  userId: string | null;
}

const tiers = [
  {
    name: "Local",
    price: "€0",
    sub: "Forever",
    items: ["Local install", "Basic memory workflows", "Community support"],
    cta: "Start Local",
    href: "https://github.com/drizzoai-afk/matriosha",
  },
  {
    name: "Standard",
    price: "€9",
    sub: "per month + overages",
    items: ["Managed sync", "Usage dashboard", "Hot/cold pricing controls"],
    cta: "Get Standard",
    href: "https://accounts.matriosha.in/sign-up",
  },
  {
    name: "Enterprise",
    price: "Custom",
    sub: "Contact sales",
    items: ["Custom limits", "Security reviews", "Priority support"],
    cta: "Contact",
    href: "mailto:drizzo.ai@gmail.com",
  },
];

export function PricingSection({ userId }: PricingSectionProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Pricing</h2>
        <p className="mt-2 text-sm text-muted-foreground">Choose a plan that matches your memory throughput.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {tiers.map((tier) => (
          <Card key={tier.name} className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">{tier.name}</CardTitle>
              <p className="text-2xl font-semibold text-cyan-300">{tier.price}</p>
              <p className="text-xs text-muted-foreground">{tier.sub}</p>
            </CardHeader>
            <CardContent className="space-y-4">
              <ul className="space-y-1 text-sm text-muted-foreground">
                {tier.items.map((item) => (
                  <li key={item}>• {item}</li>
                ))}
              </ul>
              <Link href={tier.name === "Standard" && userId ? "/dashboard" : tier.href} target={tier.href.startsWith("http") || tier.href.startsWith("mailto") ? "_blank" : undefined}>
                <Button variant={tier.name === "Standard" ? "default" : "outline"} className={tier.name === "Standard" ? "w-full bg-cyan-500 text-black hover:bg-cyan-400" : "w-full"}>
                  {tier.cta}
                </Button>
              </Link>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
