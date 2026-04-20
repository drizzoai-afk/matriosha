import { SignInButton, SignUpButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Check, Shield, Database, Lock } from "lucide-react";

export default async function Home() {
  const { userId } = await auth();

  return (
    <main className="min-h-screen bg-[#080808] text-white selection:bg-cyan-500/30">
      {/* Header */}
      <header className="border-b border-zinc-800/50 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="font-mono font-bold text-xl text-cyan-400 tracking-tighter">MATRIOSHA</div>
          <nav className="hidden md:flex gap-6 text-sm text-zinc-400">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#pricing" className="hover:text-white transition-colors">Pricing</a>
            <a href="https://github.com/drizzoai-afk/matriosha" target="_blank" rel="noreferrer" className="hover:text-white transition-colors">GitHub</a>
          </nav>
          {!userId ? (
            <div className="flex gap-2">
              <SignInButton mode="modal">
                <Button variant="ghost" size="sm" className="text-zinc-300">Log In</Button>
              </SignInButton>
              <SignUpButton mode="modal">
                <Button size="sm" className="bg-cyan-600 hover:bg-cyan-700 text-white">Get Started</Button>
              </SignUpButton>
            </div>
          ) : (
            <a href="/dashboard">
              <Button size="sm" className="bg-cyan-600 hover:bg-cyan-700 text-white">Dashboard</Button>
            </a>
          )}
        </div>
      </header>

      {/* Hero */}
      <section className="pt-32 pb-20 px-6 text-center">
        <div className="max-w-4xl mx-auto space-y-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-xs font-mono text-cyan-400">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
            </span>
            v1.0 Secure Agentic Memory
          </div>
          <h1 className="text-5xl md:text-7xl font-bold tracking-tight text-white">
            Sovereign Memory for <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-fuchsia-500">AI Agents</span>
          </h1>
          <p className="text-xl text-zinc-400 max-w-2xl mx-auto leading-relaxed">
            Encrypt, verify, and forget. The immutable memory layer that ensures your agents never hallucinate the past.
          </p>
          <div className="flex justify-center gap-4 pt-4">
            {!userId ? (
              <>
                <SignUpButton mode="modal">
                  <Button size="lg" className="bg-white text-black hover:bg-zinc-200 font-semibold">Start Building</Button>
                </SignUpButton>
                <SignInButton mode="modal">
                  <Button size="lg" variant="outline" className="border-zinc-700 text-zinc-300 hover:bg-zinc-900">View Demo</Button>
                </SignInButton>
              </>
            ) : (
              <a href="/dashboard">
                <Button size="lg" className="bg-cyan-600 hover:bg-cyan-700 text-white">Go to Dashboard</Button>
              </a>
            )}
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section id="features" className="py-20 px-6 border-t border-zinc-800/50">
        <div className="max-w-7xl mx-auto grid md:grid-cols-3 gap-8">
          {[
            { icon: Lock, title: "AES-256-GCM Encryption", desc: "Client-side encryption ensures only you hold the keys to your agent's memory." },
            { icon: Shield, title: "Merkle Tree Integrity", desc: "Cryptographic proof of data immutability. Detect any tampering instantly." },
            { icon: Database, title: "Agentic RAG Ready", desc: "Optimized for high-context retrieval with semantic pruning and compression." }
          ].map((f, i) => (
            <Card key={i} className="bg-zinc-900/50 border-zinc-800 hover:border-cyan-500/50 transition-colors group">
              <CardHeader>
                <f.icon className="w-10 h-10 text-cyan-400 mb-4 group-hover:scale-110 transition-transform" />
                <CardTitle className="text-white">{f.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-zinc-400">{f.desc}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-20 px-6 border-t border-zinc-800/50 bg-zinc-900/20">
        <div className="max-w-7xl mx-auto text-center space-y-12">
          <div className="space-y-4">
            <h2 className="text-3xl md:text-4xl font-bold text-white">Simple, Scalable Pricing</h2>
            <p className="text-zinc-400">Choose the memory capacity your agents need.</p>
          </div>
          
          <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {/* Local Plan */}
            <Card className="bg-[#080808] border-zinc-800 flex flex-col">
              <CardHeader>
                <CardTitle className="text-zinc-300">Local</CardTitle>
                <div className="text-3xl font-bold text-white mt-2">Free</div>
              </CardHeader>
              <CardContent className="flex-1 space-y-4">
                <ul className="space-y-3 text-sm text-zinc-400 text-left">
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Local-only storage</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Basic encryption</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Single agent support</li>
                </ul>
              </CardContent>
            </Card>

            {/* Standard Plan */}
            <Card className="bg-zinc-900 border-cyan-500/50 relative flex flex-col shadow-2xl shadow-cyan-900/20">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-cyan-600 text-white text-xs font-bold px-3 py-1 rounded-full">MOST POPULAR</div>
              <CardHeader>
                <CardTitle className="text-white">Standard</CardTitle>
                <div className="text-3xl font-bold text-white mt-2">€9<span className="text-lg text-zinc-500 font-normal">/mo</span></div>
              </CardHeader>
              <CardContent className="flex-1 space-y-4">
                <ul className="space-y-3 text-sm text-zinc-300 text-left">
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> 5GB Encrypted Vault</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Merkle Tree Verification</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Up to 5 Agents</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> API Access</li>
                </ul>
                <SignUpButton mode="modal">
                  <Button className="w-full bg-cyan-600 hover:bg-cyan-700 text-white mt-4">Subscribe Now</Button>
                </SignUpButton>
              </CardContent>
            </Card>

            {/* Enterprise Plan */}
            <Card className="bg-[#080808] border-zinc-800 flex flex-col">
              <CardHeader>
                <CardTitle className="text-zinc-300">Enterprise</CardTitle>
                <div className="text-3xl font-bold text-white mt-2">Custom</div>
              </CardHeader>
              <CardContent className="flex-1 space-y-4">
                <ul className="space-y-3 text-sm text-zinc-400 text-left">
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Unlimited Storage</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> Dedicated Infrastructure</li>
                  <li className="flex gap-2"><Check className="w-4 h-4 text-cyan-500" /> SSO & Audit Logs</li>
                </ul>
                <Button variant="outline" className="w-full border-zinc-700 text-zinc-300 hover:bg-zinc-900 mt-4">Contact Sales</Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-zinc-800/50 text-center text-zinc-500 text-sm">
        <p>&copy; 2026 Matriosha. Built for sovereign AI.</p>
      </footer>
    </main>
  );
}
