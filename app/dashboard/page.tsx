"use client";

import { useState, useEffect } from "react";
import { useAuth, SignInButton, UserButton } from "@clerk/nextjs";
import { ShieldCheck, Terminal, ArrowDown, Database, Lock, Activity, Loader2 } from "lucide-react";
import { VaultIntegrityCard } from "@/components/VaultIntegrityCard";
import { StorageTierVisualizer } from "@/components/StorageTierVisualizer";
import { createBrowserClient } from "@supabase/ssr";

export default function DashboardPage() {
  const { isSignedIn, isLoaded } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [subscription, setSubscription] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const supabase = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 50);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    if (isSignedIn) {
      const fetchSubscription = async () => {
        try {
          // In a real app, you'd join with the users table or use the Clerk ID directly
          const { data, error } = await supabase
            .from('subscriptions')
            .select('*')
            .eq('user_id', isSignedIn) // Assuming user_id matches Clerk ID or is mapped
            .single();
          
          if (!error && data) setSubscription(data);
        } catch (err) {
          console.error(err);
        } finally {
          setLoading(false);
        }
      };
      fetchSubscription();
    }
  }, [isSignedIn, supabase]);

  const handleCheckout = async () => {
    try {
      const res = await fetch('/api/create-checkout-session', { method: 'POST' });
      const data = await res.json();
      if (data.url) window.location.href = data.url;
    } catch (err) {
      console.error(err);
    }
  };

  if (!isLoaded || loading) {
    return (
      <div className="min-h-screen bg-[#080808] flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
      </div>
    );
  }

  if (!isSignedIn) {
    return (
      <div className="min-h-screen bg-[#080808] flex flex-col items-center justify-center text-white space-y-6">
        <ShieldCheck className="w-16 h-16 text-zinc-700" />
        <h1 className="text-2xl font-bold">Access Required</h1>
        <SignInButton mode="modal">
          <button className="px-6 py-3 bg-white text-black font-bold rounded-lg hover:bg-zinc-200 transition-colors">
            Sign In to Matriosha
          </button>
        </SignInButton>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#080808] text-zinc-100 font-sans selection:bg-cyan-500/30">
      {/* Grain Overlay */}
      <div className="fixed inset-0 z-[-1] opacity-[0.04] pointer-events-none" 
           style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")` }} />

      {/* Navigation */}
      <nav className={`fixed top-0 w-full z-50 transition-all duration-500 ${scrolled ? 'bg-[#080808]/90 backdrop-blur-md border-b border-white/5 py-4' : 'bg-transparent py-8'}`}>
        <div className="max-w-7xl mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-6 h-6 text-cyan-400" />
            <span className="text-lg font-bold tracking-tight">Matriosha<span className="text-fuchsia-500">.OS</span></span>
          </div>
          <UserButton />
        </div>
      </nav>

      <main className="pt-32 px-6 pb-20">
        <div className="max-w-7xl mx-auto">
          
          {!subscription || subscription.status !== 'active' ? (
            /* UNPAID STATE */
            <div className="max-w-2xl mx-auto text-center space-y-8 animate-in fade-in zoom-in duration-700">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-fuchsia-500/20 bg-fuchsia-500/5 text-xs font-mono text-fuchsia-400">
                <Lock className="w-3 h-3" /> VAULT LOCKED
              </div>
              <h1 className="text-5xl font-bold tracking-tighter">Activate your memory layer.</h1>
              <p className="text-xl text-zinc-400">
                Start with the Standard Plan. Secure, encrypted, and ready for your agents.
              </p>
              
              <div className="bg-[#0f0f0f] border border-white/10 rounded-2xl p-8 mt-8 text-left space-y-6">
                <div className="flex justify-between items-center border-b border-white/5 pb-6">
                  <div>
                    <h3 className="text-lg font-bold">Standard Plan</h3>
                    <p className="text-sm text-zinc-500">For individual developers</p>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold">$9<span className="text-sm text-zinc-500 font-normal">/mo</span></div>
                  </div>
                </div>
                <ul className="space-y-3 text-sm text-zinc-400">
                  <li className="flex items-center gap-2"><ShieldCheck className="w-4 h-4 text-cyan-400" /> 2GB Hot Storage (Supabase)</li>
                  <li className="flex items-center gap-2"><Database className="w-4 h-4 text-fuchsia-400" /> Unlimited Cold Archive (R2)</li>
                  <li className="flex items-center gap-2"><Lock className="w-4 h-4 text-green-400" /> AES-256-GCM Encryption</li>
                </ul>
                <button 
                  onClick={handleCheckout}
                  className="w-full py-4 bg-white text-black font-bold rounded-lg hover:bg-zinc-200 transition-colors flex items-center justify-center gap-2"
                >
                  Activate Standard Plan <ArrowDown className="w-4 h-4 -rotate-90" />
                </button>
              </div>
            </div>
          ) : (
            /* ACTIVE STATE */
            <div className="space-y-24 animate-in fade-in slide-in-from-bottom-8 duration-1000">
              {/* Hero Status */}
              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-green-500/20 bg-green-500/5 text-xs font-mono text-green-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                  SYSTEM ONLINE
                </div>
                <h1 className="text-4xl md:text-6xl font-bold tracking-tighter">Welcome back, Agent.</h1>
              </div>

              {/* Modules */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <VaultIntegrityCard />
                <StorageTierVisualizer />
              </div>

              {/* CLI Command Center */}
              <div className="border border-white/10 bg-[#0f0f0f] rounded-2xl overflow-hidden">
                <div className="bg-white/5 px-6 py-4 border-b border-white/10 flex justify-between items-center">
                  <span className="text-xs font-mono uppercase text-zinc-400 flex items-center gap-2 tracking-widest">
                    <Terminal className="w-4 h-4" /> Command Center
                  </span>
                  <span className="text-[10px] text-zinc-600 font-mono">v1.0.0</span>
                </div>
                <div className="p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {[
                    { cmd: 'matriosha init', desc: 'Initialize a new secure vault' },
                    { cmd: 'matriosha remember "note"', desc: 'Store an encrypted memory block' },
                    { cmd: 'matriosha recall "query"', desc: 'Semantic search with Merkle verification' },
                    { cmd: 'matriosha sync', desc: 'Push local changes to the cloud' },
                    { cmd: 'matriosha verify', desc: 'Check integrity against the root hash' },
                    { cmd: 'matriosha status', desc: 'View storage usage and tier status' }
                  ].map((item, i) => (
                    <div key={i} className="group space-y-2">
                      <div className="flex items-center justify-between p-3 bg-black/40 border border-white/5 group-hover:border-cyan-500/30 transition-all rounded-md font-mono text-sm text-cyan-400 cursor-pointer select-all">
                        <span>$ {item.cmd}</span>
                      </div>
                      <p className="text-xs text-zinc-500 pl-1">{item.desc}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}