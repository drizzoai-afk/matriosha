import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-border/70 py-12">
      <div className="mx-auto grid max-w-6xl gap-8 px-6 text-sm text-muted-foreground md:grid-cols-4">
        <div>
          <h3 className="mb-2 font-medium text-foreground">Product</h3>
          <ul className="space-y-1">
            <li><a href="#features">Features</a></li>
            <li><a href="#pricing">Pricing</a></li>
            <li><Link href="/dashboard">Dashboard</Link></li>
          </ul>
        </div>
        <div>
          <h3 className="mb-2 font-medium text-foreground">Resources</h3>
          <ul className="space-y-1">
            <li><Link href="https://github.com/drizzoai-afk/matriosha" target="_blank" rel="noreferrer">GitHub</Link></li>
            <li><Link href="/sign-in">Sign In</Link></li>
            <li><Link href="/sign-up">Sign Up</Link></li>
          </ul>
        </div>
        <div>
          <h3 className="mb-2 font-medium text-foreground">Legal</h3>
          <ul className="space-y-1">
            <li><Link href="/privacy">Privacy</Link></li>
            <li><Link href="/terms">Terms</Link></li>
            <li><Link href="/security">Security</Link></li>
          </ul>
        </div>
        <div>
          <h3 className="mb-2 font-medium text-foreground">Connect</h3>
          <ul className="space-y-1">
            <li><Link href="mailto:drizzo.ai@gmail.com">Email</Link></li>
            <li><Link href="https://github.com/drizzoai-afk/matriosha" target="_blank" rel="noreferrer">Open Source</Link></li>
          </ul>
        </div>
      </div>
    </footer>
  );
}
