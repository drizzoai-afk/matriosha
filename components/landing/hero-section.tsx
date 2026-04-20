import Link from "next/link";
import { Button } from "@/components/ui/button";

interface HeroSectionProps {
  userId: string | null;
}

export function HeroSection({ userId }: HeroSectionProps) {
  return (
    <section className="mx-auto max-w-6xl px-6 pb-20 pt-24 text-center">
      <p className="mx-auto mb-6 inline-flex rounded-full border border-cyan-400/25 bg-cyan-400/10 px-3 py-1 font-mono text-xs text-cyan-300">
        Zero-knowledge agentic memory system
      </p>

      <h1 className="text-balance text-4xl font-semibold tracking-tight md:text-6xl">
        Own your data. Switch agent with no effort.
      </h1>
      <p className="mx-auto mt-4 max-w-2xl text-balance text-lg text-muted-foreground">
        One memory format. Every AI model. No adapters needed.
      </p>

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Link href={userId ? "/dashboard" : "https://accounts.matriosha.in/sign-up"}>
          <Button className="bg-cyan-500 text-black hover:bg-cyan-400">Launch Dashboard</Button>
        </Link>
        <a href="#quick-start">
          <Button variant="outline" className="border-fuchsia-400/50 text-fuchsia-200 hover:bg-fuchsia-400/10">Quick Start</Button>
        </a>
      </div>
    </section>
  );
}
