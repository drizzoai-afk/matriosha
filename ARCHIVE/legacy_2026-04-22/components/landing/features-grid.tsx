import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const features = [
  {
    title: "Model-Agnostic Protocol",
    body: "A single memory format designed for cross-agent portability.",
  },
  {
    title: "Zero-Knowledge",
    body: "Encrypted payload architecture keeps plaintext outside the platform boundary.",
  },
  {
    title: "Merkle Integrity",
    body: "Cryptographic root verification ensures vault consistency over time.",
  },
  {
    title: "Hot/Cold Storage",
    body: "Fast hot tier plus cost-efficient cold archive workflows.",
  },
  {
    title: "Local-First",
    body: "Run local workflows without lock-in, then scale to managed infrastructure.",
  },
  {
    title: "Open Source",
    body: "Transparent implementation with auditable behavior and reproducible setup.",
  },
];

export function FeaturesGrid() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Features</h2>
        <p className="mt-2 text-sm text-muted-foreground">Built for sovereign, verifiable, and portable memory flows.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {features.map((feature) => (
          <Card key={feature.title} className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">{feature.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{feature.body}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
