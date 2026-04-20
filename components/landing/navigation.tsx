import Link from "next/link";
import { Button } from "@/components/ui/button";

interface LandingNavigationProps {
  userId: string | null;
}

export function LandingNavigation({ userId }: LandingNavigationProps) {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-[--bg-base]/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link href="/" className="font-mono text-sm tracking-[0.16em] text-cyan-300">
          MATRIOSHA
        </Link>

        <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex">
          <a href="#features" className="hover:text-foreground">Features</a>
          <a href="#pricing" className="hover:text-foreground">Pricing</a>
          <Link href="https://github.com/drizzoai-afk/matriosha" target="_blank" rel="noreferrer" className="hover:text-foreground">
            GitHub
          </Link>
        </nav>

        <div className="flex items-center gap-2">
          <Link href={userId ? "/dashboard" : "/sign-in"}>
            <Button variant="ghost" className="text-zinc-300 hover:text-white">Sign In</Button>
          </Link>
          <Link href={userId ? "/dashboard" : "/sign-up"}>
            <Button className="bg-cyan-500 text-black hover:bg-cyan-400">Get Started</Button>
          </Link>
        </div>
      </div>
    </header>
  );
}
