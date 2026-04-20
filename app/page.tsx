import { SignInButton, SignUpButton } from "@clerk/nextjs";
import { ShieldCheck, Terminal, Zap, Lock, Check, ArrowRight } from "lucide-react";
import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-white selection:bg-cyan-500/30">
      {/* Grain Overlay */}
      <div className="fixed inset-0 opacity-[0.03] pointer-events-none z-0" style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")` }}></div>

      {/* Navbar */}
      <nav className="relative z-10 border-b border-zinc-800/50 bg-zinc-950/80 backdrop-blur-md sticky top-0">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-cyan-500" />
            <span className="font-bold tracking-tight text-lg">Matriosha</span>
          </div>
          <div className="flex items-center gap-4">
            <SignInButton mode="modal">
              <button className="text-sm font-medium text-zinc-400 hover:text-white transition-colors">
                Log in
              </button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="bg-white text-black px-4 py-2 rounded-md text-sm font-semibold hover:bg-zinc-200 transition-all shadow-[0_0_15px_rgba(255,255,255,0.1)]">
                Get Started
              </button>
            </SignUpButton>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <main className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 pt-20 md:pt-32 pb-24">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
          <div className="space-y-8">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-xs font-mono text-cyan-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
              </span>
              v1.0.0 — Stable Release
            </div>
            
            <h1 className="text-4xl md:text-6xl lg:text-7xl font-bold tracking-tighter leading-[1.1]">
              The Sovereign <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-fuchsia-500">
                Memory Layer
              </span>
            </h1>
            
            <p className="text-xl text-zinc-400 max-w-lg leading-relaxed">
              Secure, encrypted, and verifiable long-term memory for your AI agents. 
              Stop letting your data vanish into the void.
            </p>

            <div className="flex flex-wrap gap-4 pt-4">
              <SignUpButton mode="modal">
                <button className="bg-cyan-500 text-black px-8 py-3 rounded-md font-bold hover:bg-cyan-400 transition-all flex items-center gap-2">
                  Start Building <Zap className="w-4 h-4" />
                </button>
              </SignUpButton>
              <Link href="https://github.com/drizzoai-afk/matriosha" target="_blank">
                <button className="px-8 py-3 rounded-md font-bold border border-zinc-700 hover:border-zinc-500 hover:bg-zinc-900 transition-all text-zinc-300">
                  View Documentation
                </button>
              </Link>
            </div>
          </div>

          {/* Install Commands */}
          <div className="relative group mt-8 lg:mt-0">
            <div className="absolute -inset-1 bg-gradient-to-r from-cyan-500 to-fuchsia-500 rounded-xl blur opacity-20 group-hover:opacity-40 transition duration-1000"></div>
            <div className="relative bg-zinc-900 border border-zinc-800 rounded-xl p-6 font-mono text-xs sm:text-sm shadow-2xl overflow-x-auto">
              <div className="flex items-center gap-2 mb-4 border-b border-zinc-800 pb-4">
                <Terminal className="w-4 h-4 text-zinc-500" />
                <span className="text-zinc-500">install.sh</span>
              </div>
              <div className="space-y-3 text-zinc-300">
                <div className="space-y-1">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-wider">macOS (Homebrew)</p>
                  <p><span className="text-green-400">$</span> brew install matriosha/tap/matriosha</p>
                </div>
                <div className="space-y-1">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-wider">npm</p>
                  <p><span className="text-green-400">$</span> npx matriosha@latest init</p>
                </div>
                <div className="space-y-1">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-wider">Docker</p>
                  <p><span className="text-green-400">$</span> docker run -it ghcr.io/matriosha/cli init</p>
                </div>
                <div className="space-y-1">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-wider">Windows (Scoop)</p>
                  <p><span className="text-green-400">$</span> scoop bucket add matriosha https://github.com/matriosha/scoop-bucket.git</p>
                  <p><span className="text-green-400">$</span> scoop install matriosha</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Feature Grid */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6 mt-20 md:mt-32 pt-16 border-t border-zinc-800/50">
          {[
            {
              icon: <Lock className="w-6 h-6 text-fuchsia-500" />,
              title: "Vendor Lock-in Freedom",
              desc: "Your memory is portable. Switch LLMs or agents without losing your history."
            },
            {
              icon: <ShieldCheck className="w-6 h-6 text-cyan-500" />,
              title: "Anti-Prompt Injection",
              desc: "Cryptographic signatures ensure your agent only reads verified, untampered context."
            },
            {
              icon: <Terminal className="w-6 h-6 text-green-500" />,
              title: "Multi-Agent Support",
              desc: "One vault for all your agents. Share context securely across different personas."
            },
            {
              icon: <Zap className="w-6 h-6 text-yellow-500" />,
              title: "Portable Memory",
              desc: "Export your entire vault as encrypted binary files. You own the data."
            }
          ].map((f, i) => (
            <div key={i} className="p-6 rounded-xl bg-zinc-900/50 border border-zinc-800 hover:border-zinc-700 transition-all group">
              <div className="mb-4 p-3 rounded-lg bg-zinc-950 border border-zinc-800 w-fit group-hover:scale-110 transition-transform">
                {f.icon}
              </div>
              <h3 className="text-lg font-bold mb-2 text-zinc-100">{f.title}</h3>
              <p className="text-sm text-zinc-400 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>

        {/* Pricing Section */}
        <div className="mt-20 md:mt-32 pt-16 border-t border-zinc-800/50">
          <div className="text-center mb-16 space-y-4">
            <h2 className="text-3xl md:text-5xl font-bold tracking-tighter">Simple, Scalable Pricing</h2>
            <p className="text-zinc-400 max-w-2xl mx-auto text-lg">Choose the memory layer that fits your needs. From local sovereignty to enterprise scale.</p>
          </div>

          <div className="grid md:grid-cols-3 gap-8 max-w-6xl mx-auto">
            {/* Free Tier */}
            <div className="p-8 rounded-2xl bg-zinc-900/30 border border-zinc-800 flex flex-col">
              <div className="mb-8">
                <h3 className="text-xl font-bold text-zinc-100">Local</h3>
                <p className="text-sm text-zinc-500 mt-2">Total control. Your data, your hardware.</p>
              </div>
              <div className="mb-8">
                <span className="text-4xl font-bold text-white">$0</span>
                <span className="text-zinc-500 ml-2">/ month</span>
              </div>
              <ul className="space-y-4 mb-8 flex-1">
                {[
                  "Unlimited Local Storage",
                  "AES-256-GCM Encryption",
                  "Manual File Management",
                  "You hold the keys"
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm text-zinc-300">
                    <Check className="w-5 h-5 text-zinc-600 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
              <button className="w-full py-3 rounded-lg border border-zinc-700 font-semibold hover:bg-zinc-800 transition-colors text-zinc-300">
                Get Started
              </button>
            </div>

            {/* Standard Tier */}
            <div className="relative p-8 rounded-2xl bg-zinc-900 border border-cyan-500/30 flex flex-col shadow-[0_0_40px_-10px_rgba(6,182,212,0.15)]">
              <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-cyan-500 text-black text-xs font-bold rounded-full uppercase tracking-wider">
                Most Popular
              </div>
              <div className="mb-8">
                <h3 className="text-xl font-bold text-white">Standard</h3>
                <p className="text-sm text-zinc-500 mt-2">The sovereign memory layer for your agents.</p>
              </div>
              <div className="mb-8">
                <span className="text-4xl font-bold text-white">$9</span>
                <span className="text-zinc-500 ml-2">/ month</span>
              </div>
              <ul className="space-y-4 mb-8 flex-1">
                {[
                  "2 GB Hot Storage (Supabase)",
                  "1 GB Cold Storage (R2)",
                  "Key Escrow & Recovery",
                  "Real-time Merkle Verification",
                  "Overage: €6/GB (Hot) • €3/GB (Cold)"
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm text-zinc-200">
                    <Check className="w-5 h-5 text-cyan-400 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
              <SignUpButton mode="modal">
                <button className="w-full py-3 rounded-lg bg-cyan-500 text-black font-bold hover:bg-cyan-400 transition-colors flex items-center justify-center gap-2">
                  Start Building <ArrowRight className="w-4 h-4" />
                </button>
              </SignUpButton>
            </div>

            {/* Enterprise Tier */}
            <div className="p-8 rounded-2xl bg-zinc-900/30 border border-zinc-800 flex flex-col">
              <div className="mb-8">
                <h3 className="text-xl font-bold text-zinc-100">Enterprise</h3>
                <p className="text-sm text-zinc-500 mt-2">For teams and large-scale integrations.</p>
              </div>
              <div className="mb-8">
                <span className="text-4xl font-bold text-white">Custom</span>
              </div>
              <ul className="space-y-4 mb-8 flex-1">
                {[
                  "Custom Storage Limits",
                  "Dedicated Instances",
                  "Direct Support Line",
                  "SLA & Uptime Guarantees",
                  "Advanced Audit Logs"
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-3 text-sm text-zinc-300">
                    <Check className="w-5 h-5 text-zinc-600 shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
              <a href="mailto:drizzo.ai@gmail.com" className="w-full py-3 rounded-lg border border-zinc-700 font-semibold hover:bg-zinc-800 transition-colors text-center text-zinc-300">
                Contact Sales
              </a>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="mt-32 pt-8 border-t border-zinc-800/50 flex flex-col md:flex-row justify-between items-center gap-4 text-sm text-zinc-500">
          <p>© 2026 Matriosha. All rights reserved.</p>
          <div className="flex gap-6">
            <Link href="/legal/impressum" className="hover:text-zinc-300 transition-colors">Impressum</Link>
            <Link href="/legal/privacy" className="hover:text-zinc-300 transition-colors">Privacy Policy</Link>
          </div>
        </footer>
      </main>
    </div>
  );
}