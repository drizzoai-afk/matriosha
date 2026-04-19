import { SignInButton, SignUpButton } from "@clerk/nextjs";
import { ShieldCheck, Terminal, Zap, Lock } from "lucide-react";
import Link from "next/link";

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-zinc-950 text-white selection:bg-cyan-500/30">
      {/* Grain Overlay */}
      <div className="fixed inset-0 opacity-[0.03] pointer-events-none z-0" style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")` }}></div>

      {/* Navbar */}
      <nav className="relative z-10 border-b border-zinc-800/50 bg-zinc-950/50 backdrop-blur-md sticky top-0">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
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
      <main className="relative z-10 max-w-7xl mx-auto px-6 pt-32 pb-24">
        <div className="grid lg:grid-cols-2 gap-16 items-center">
          <div className="space-y-8">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-xs font-mono text-cyan-400">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
              </span>
              v1.0.0 — Stable Release
            </div>
            
            <h1 className="text-5xl md:text-7xl font-bold tracking-tighter leading-[1.1]">
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

          {/* CLI Preview Card */}
          <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-cyan-500 to-fuchsia-500 rounded-lg blur opacity-20 group-hover:opacity-40 transition duration-1000"></div>
            <div className="relative bg-zinc-900 border border-zinc-800 rounded-lg p-6 font-mono text-sm shadow-2xl">
              <div className="flex items-center gap-2 mb-4 border-b border-zinc-800 pb-4">
                <Terminal className="w-4 h-4 text-zinc-500" />
                <span className="text-zinc-500">bash — 80x24</span>
              </div>
              <div className="space-y-2 text-zinc-300">
                <p><span className="text-green-400">➜</span> <span className="text-cyan-400">~</span> npx matriosha init</p>
                <p className="text-zinc-500">Initializing secure vault...</p>
                <p className="text-zinc-500">Generating AES-256-GCM keys...</p>
                <p><span className="text-green-400">✓</span> Vault created at <span className="text-fuchsia-400">./memory/vault.db</span></p>
                <p><span className="text-green-400">✓</span> Merkle root synced to R2</p>
                <p className="animate-pulse mt-4"><span className="text-green-400">➜</span> <span className="text-cyan-400">~</span> <span className="w-2 h-4 bg-zinc-500 inline-block align-middle"></span></p>
              </div>
            </div>
          </div>
        </div>

        {/* Feature Grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6 mt-32 pt-16 border-t border-zinc-800/50">
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
              desc: "Export your entire knowledge base as encrypted JSONL. You own the data."
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