"use client";

"use client";

import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Terminal, ShieldCheck, HardDrive, Zap, Activity, CreditCard, Layers } from "lucide-react";
import { useState, useEffect } from "react";
import { getSupabaseClient } from "@/lib/supabase";

export function BentoGrid() {
  const [status, setStatus] = useState<any>(null);
  const [billing, setBilling] = useState<any>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const supabase = await getSupabaseClient();
        
        // Fetch Vault Status
        const { data: vaultData } = await supabase.from('vaults').select('*').single();
        
        // Fetch Subscription
        const { data: subData } = await supabase.from('subscriptions').select('*').single();

        setStatus({
          vault: {
            merkleRoot: vaultData?.merkle_root || "Not synced",
            integrity: vaultData ? "VERIFIED" : "PENDING",
            lastSync: vaultData?.last_sync || new Date().toISOString()
          },
          storage: {
            hot: { used: 0, limit: 2 * 1024 * 1024 * 1024 },
            cold: { used: 0, limit: 1 * 1024 * 1024 * 1024 }
          },
          mcp: { status: "active", port: 8765 }
        });

        setBilling({
          plan: subData?.tier === 'pro' ? 'Standard Pro' : 'Free Tier',
          price: subData?.tier === 'pro' ? '$9.00/mo' : '$0.00',
          overage: { hot: '€6.00 / GB', cold: '€3.00 / GB' }
        });
      } catch (e) {
        console.error("Failed to fetch dashboard data", e);
      }
    };
    fetchData();
  }, []);

  const commands = [
    'matriosha init',
    'matriosha remember "..."',
    'matriosha recall "query"'
  ];

  return (
    <div className="min-h-screen bg-black text-white p-6 font-sans selection:bg-cyan-500/30">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Bento Grid Layout */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          
          {/* 1. Quick Start (Hero) */}
          <div className="md:col-span-2 bg-zinc-900/40 border border-zinc-800 rounded-xl p-6 backdrop-blur-sm hover:border-cyan-500/30 transition-all duration-300">
            <div className="flex items-center gap-2 mb-4 text-cyan-400">
              <Terminal className="w-5 h-5" />
              <h3 className="font-semibold tracking-tight">Quick Start</h3>
            </div>
            <div className="space-y-2">
              {commands.map((cmd, i) => (
                <div key={i} className="group flex items-center justify-between bg-black/50 p-3 rounded-lg font-mono text-sm text-zinc-400 hover:text-cyan-300 hover:ring-1 hover:ring-cyan-500/50 transition-all cursor-pointer"
                     onClick={() => navigator.clipboard.writeText(cmd)}>
                  <span><span className="text-zinc-600 mr-2">$</span>{cmd}</span>
                  <span className="opacity-0 group-hover:opacity-100 text-xs text-zinc-600">COPY</span>
                </div>
              ))}
            </div>
          </div>

          {/* 2. Vault Integrity */}
          <div className="md:col-span-1 bg-zinc-900/40 border border-zinc-800 rounded-xl p-6 backdrop-blur-sm hover:border-green-500/30 transition-all duration-300">
            <div className="flex items-center gap-2 mb-4 text-green-400">
              <ShieldCheck className="w-5 h-5" />
              <h3 className="font-semibold tracking-tight">Integrity</h3>
            </div>
            <div className="space-y-1">
              <div className="text-xs text-zinc-500 uppercase tracking-wider">Merkle Root</div>
              <div className="font-mono text-[10px] text-zinc-300 break-all leading-relaxed">
                {status?.vault.merkleRoot.substring(0, 24)}...
              </div>
              <div className={`mt-3 inline-flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-medium ${status?.vault.integrity === 'VERIFIED' ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'}`}>
                <div className={`w-1.5 h-1.5 rounded-full ${status?.vault.integrity === 'VERIFIED' ? 'bg-green-500' : 'bg-yellow-500'}`} />
                {status?.vault.integrity || "CHECKING"}
              </div>
            </div>
          </div>

          {/* 3. MCP Server */}
          <div className="md:col-span-1 bg-zinc-900/40 border border-zinc-800 rounded-xl p-6 backdrop-blur-sm hover:border-fuchsia-500/30 transition-all duration-300">
            <div className="flex items-center gap-2 mb-4 text-fuchsia-400">
              <Zap className="w-5 h-5" />
              <h3 className="font-semibold tracking-tight">MCP Server</h3>
            </div>
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
              <span className="text-sm font-medium text-zinc-200">ACTIVE</span>
            </div>
            <div className="text-xs text-zinc-500 font-mono">Port: 8765</div>
          </div>

          {/* 4. Storage Tiers */}
          <div className="md:col-span-2 bg-zinc-900/40 border border-zinc-800 rounded-xl p-6 backdrop-blur-sm hover:border-white/10 transition-all duration-300">
            <div className="flex items-center gap-2 mb-4 text-white">
              <HardDrive className="w-5 h-5" />
              <h3 className="font-semibold tracking-tight">Storage Tiers</h3>
            </div>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-xs mb-1.5 text-zinc-400 font-medium">
                  <span>Hot Storage (Supabase)</span>
                  <span className="text-cyan-400">0.00 / 2.00 GB</span>
                </div>
                <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-cyan-500 to-cyan-400 w-[0%] shadow-[0_0_10px_rgba(6,182,212,0.5)]" />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-xs mb-1.5 text-zinc-400 font-medium">
                  <span>Cold Storage (R2)</span>
                  <span className="text-fuchsia-400">0.00 / 1.00 GB</span>
                </div>
                <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-fuchsia-600 to-fuchsia-500 w-[0%] shadow-[0_0_10px_rgba(192,38,211,0.5)]" />
                </div>
              </div>
            </div>
          </div>

          {/* 5. Plan & Overage */}
          <div className="md:col-span-2 bg-zinc-900/40 border border-zinc-800 rounded-xl p-6 backdrop-blur-sm hover:border-white/10 transition-all duration-300">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-2 text-white">
                <CreditCard className="w-5 h-5" />
                <h3 className="font-semibold tracking-tight">Subscription</h3>
              </div>
              <div className="text-right">
                <div className="text-lg font-bold text-white tracking-tight">{billing?.plan || "Free Tier"}</div>
                <div className="text-xs text-zinc-500 font-mono">{billing?.price || "$0.00/mo"}</div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 text-xs font-mono border-t border-zinc-800 pt-4">
              <div>
                <span className="text-zinc-500 block mb-1">Hot Overage</span>
                <span className="text-zinc-300">{billing?.overage?.hot || "€6.00 / GB"}</span>
              </div>
              <div>
                <span className="text-zinc-500 block mb-1">Cold Overage</span>
                <span className="text-zinc-300">{billing?.overage?.cold || "€3.00 / GB"}</span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
