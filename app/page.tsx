"use client";

import { useState } from "react";
import Link from "next/link";
import { ShieldCheck, Terminal, ArrowRight, Copy, Check, Lock, Database } from "lucide-react";

export default function LandingPage() {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const commands = [
    'npm install -g @matriosha/cli',
    'matriosha init',
    'matriosha remember "Meeting notes: Q2 strategy"'
  ];

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  return (
    <div className="min-h-screen bg-[#080808] text-zinc-100 font-sans selection:bg-cyan-500/30 overflow-x-hidden">
      {/* Grain Overlay */}
      <div className="fixed inset-0 z-[-1] opacity-[0.04] pointer-events-none" 
           style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")` }} />

      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 border-b border-white/5 bg-[#080808]/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-cyan-400" />
            <span className="font-bold tracking-tight">Matriosha</span>
          </div>
          <div className="flex items-center gap-6">
            <Link href="/dashboard" className="text-sm font-medium text-zinc-400 hover:text-white transition-colors">Sign In</Link>
            <Link href="/dashboard" className="px-4 py-2 bg-white text-black text-sm font-bold rounded-md hover:bg-zinc-200 transition-colors">Get Started</Link>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-7xl mx-auto text-center space-y-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-white/10 bg-white/5 text-xs font-mono text-cyan-400 animate-in fade-in zoom-in duration-700">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
            v1.2.0 IS LIVE
          </div>
          
          <h1 className="text-6xl md:text-8xl font-bold tracking-tighter leading-[0.9] animate-in fade-in slide-in-from-bottom-4 duration-1000 delay-150">
            Secure Agentic<br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-fuchsia-500">Memory Layer.</span>
          </h1>
          
          <p className="text-xl text-zinc-400 max-w-2xl mx-auto leading-relaxed animate-in fade-in slide-in-from-bottom-4 duration-1000 delay-300">
            The local-first memory vault for AI agents. Cryptographically verified, 
            hybrid-storage, and designed for the next generation of autonomous software.
          </p>
        </div>
      </section>

      {/* Quick Start Section */}
      <section className="py-20 px-6 border-t border-white/5 bg-[#0a0a0a]">
        <div className="max-w-4xl mx-auto space-y-12">
          <div className="text-center space-y-4">
            <h2 className="text-3xl font-bold tracking-tight">Quick Start</h2>
            <p className="text-zinc-400">Integrate Matriosha into your agent workflow in seconds.</p>
          </div>

          <div className="space-y-4">
            {commands.map((cmd, idx) => (
              <div 
                key={idx}
                className="group relative bg-black/40 border border-white/10 rounded-lg p-4 flex items-center justify-between font-mono text-sm text-cyan-400 hover:border-cyan-500/30 transition-all duration-300 animate-in fade-in slide-in-from-bottom-2"
                style={{ animationDelay: `${400 + (idx * 100)}ms` }}
              >
                <div className="flex items-center gap-4">
                  <Terminal className="w-4 h-4 text-zinc-600" />
                  <span>{cmd}</span>
                </div>
                <button 
                  onClick={() => copyToClipboard(cmd, idx)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity text-zinc-500 hover:text-white p-2 rounded-md hover:bg-white/10"
                >
                  {copiedIndex === idx ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-24 px-6 border-t border-white/5">
        <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="bg-[#0f0f0f] border border-white/10 rounded-2xl p-8 space-y-6 hover:border-cyan-500/20 transition-colors duration-500">
            <Lock className="w-8 h-8 text-cyan-400" />
            <h3 className="text-2xl font-bold">Cryptographic Integrity</h3>
            <p className="text-zinc-400 leading-relaxed">
              Every memory block is hashed using a Merkle tree. If the cloud record doesn't match your local state, you'll know instantly.
            </p>
          </div>
          <div className="bg-[#0f0f0f] border border-white/10 rounded-2xl p-8 space-y-6 hover:border-fuchsia-500/20 transition-colors duration-500">
            <Database className="w-8 h-8 text-fuchsia-400" />
            <h3 className="text-2xl font-bold">Hybrid Storage</h3>
            <p className="text-zinc-400 leading-relaxed">
              Hot storage on Supabase for instant recall, cold storage on Cloudflare R2 for infinite scale. Auto-archiving included.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 border-t border-white/5 text-center text-zinc-600 text-sm">
        <p>&copy; 2026 Matriosha. Built for the agentic era.</p>
      </footer>
    </div>
  );
}