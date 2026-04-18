"use client";

import { useEffect, useState } from "react";
import { Database, HardDrive, Cloud, AlertCircle } from "lucide-react";
import { createBrowserClient } from "@supabase/ssr";

// Costanti dalla SPEC.md (Sezione 8.1)
const HOT_LIMIT_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB
const COLD_LIMIT_BYTES = 1 * 1024 * 1024 * 1024; // 1 GB
const HOT_OVERAGE_RATE = 6; // €6 per GB
const COLD_OVERAGE_RATE = 3; // €3 per GB

export function StorageTierVisualizer() {
  const [usage, setUsage] = useState<{ hot: number; cold: number; overageCost: string } | null>(null);
  const supabase = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  useEffect(() => {
    const fetchBillingStatus = async () => {
      try {
        // Usiamo la vista che calcola già gli overage in centesimi
        const { data, error } = await supabase
          .from('user_billing_status')
          .select('hot_bytes, cold_bytes, overage_hot_cents, overage_cold_cents')
          .single();

        if (error) throw error;

        const totalOverageCents = (data.overage_hot_cents || 0) + (data.overage_cold_cents || 0);
        
        setUsage({
          hot: Math.round((data.hot_bytes || 0) / (1024 * 1024)), // MB per UI
          cold: Math.round((data.cold_bytes || 0) / (1024 * 1024)), // MB per UI
          overageCost: (totalOverageCents / 100).toFixed(2)
        });
      } catch (err) {
        console.error("Failed to fetch billing status:", err);
      }
    };
    fetchBillingStatus();
  }, [supabase]);

  const hotGB = usage ? (usage.hot / 1024).toFixed(2) : "0.00";
  const coldGB = usage ? (usage.cold / 1024).toFixed(2) : "0.00";
  
  const isHotOver = usage && (usage.hot * 1024 * 1024) > HOT_LIMIT_BYTES;
  const isColdOver = usage && (usage.cold * 1024 * 1024) > COLD_LIMIT_BYTES;

  return (
    <div className="relative bg-[#0f0f0f] border border-white/10 rounded-2xl p-8 overflow-hidden">
      {/* Background Glow */}
      <div className="absolute bottom-0 left-0 w-64 h-64 bg-gradient-to-tr from-fuchsia-500/10 to-transparent blur-3xl translate-y-1/2 -translate-x-1/2" />

      <div className="relative z-10 space-y-10">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <Database className="w-6 h-6 text-zinc-400" />
            <h3 className="text-sm font-bold uppercase tracking-widest text-zinc-100">Storage Tiers</h3>
          </div>
          {usage && parseFloat(usage.overageCost) > 0 && (
            <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-orange-500/10 border border-orange-500/20 text-orange-400 text-xs font-mono">
              <AlertCircle className="w-3 h-3" />
              Overage: €{usage.overageCost}/mo
            </div>
          )}
        </div>

        {/* Hot Tier */}
        <div className="space-y-3">
          <div className="flex justify-between items-end">
            <div className="flex items-center gap-3">
              <HardDrive className={`w-5 h-5 ${isHotOver ? 'text-orange-400' : 'text-cyan-400'}`} />
              <div>
                <span className="text-sm font-medium text-zinc-200 block">Hot Storage</span>
                <span className="text-[10px] text-zinc-500 font-mono">SUPABASE // LOW LATENCY</span>
              </div>
            </div>
            <span className={`text-2xl font-mono ${isHotOver ? 'text-orange-400' : 'text-cyan-400'}`}>
              {hotGB} <span className="text-sm text-zinc-600">GB</span>
            </span>
          </div>
          
          <div className="h-1.5 w-full bg-zinc-900 rounded-full overflow-hidden">
            <div 
              className={`h-full transition-all duration-1000 ease-out shadow-[0_0_15px_rgba(0,0,0,0.5)] ${isHotOver ? 'bg-orange-500 shadow-orange-500/50' : 'bg-cyan-500 shadow-cyan-500/50'}`} 
              style={{ width: usage ? `${Math.min(((usage.hot * 1024 * 1024) / HOT_LIMIT_BYTES) * 100, 100)}%` : '0%' }} 
            />
          </div>
          
          <div className="flex justify-between text-[10px] font-mono text-zinc-500 pt-2 border-t border-white/5">
            <span>LIMIT: 2 GB</span>
            {isHotOver && <span className="text-orange-400">+€6.00 / GB EXTRA</span>}
          </div>
        </div>

        {/* Cold Tier */}
        <div className="space-y-3 pt-6 border-t border-white/5">
          <div className="flex justify-between items-end">
            <div className="flex items-center gap-3">
              <Cloud className={`w-5 h-5 ${isColdOver ? 'text-orange-400' : 'text-fuchsia-400'}`} />
              <div>
                <span className="text-sm font-medium text-zinc-200 block">Cold Storage</span>
                <span className="text-[10px] text-zinc-500 font-mono">R2 // DEEP ARCHIVE</span>
              </div>
            </div>
            <span className={`text-2xl font-mono ${isColdOver ? 'text-orange-400' : 'text-fuchsia-400'}`}>
              {coldGB} <span className="text-sm text-zinc-600">GB</span>
            </span>
          </div>
          
          <div className="h-1.5 w-full bg-zinc-900 rounded-full overflow-hidden">
            <div 
              className={`h-full transition-all duration-1000 ease-out shadow-[0_0_15px_rgba(0,0,0,0.5)] ${isColdOver ? 'bg-orange-500 shadow-orange-500/50' : 'bg-fuchsia-500 shadow-fuchsia-500/50'}`} 
              style={{ width: usage ? `${Math.min(((usage.cold * 1024 * 1024) / COLD_LIMIT_BYTES) * 100, 100)}%` : '0%' }} 
            />
          </div>
          
          <div className="flex justify-between text-[10px] font-mono text-zinc-500 pt-2 border-t border-white/5">
            <span>LIMIT: 1 GB</span>
            {isColdOver && <span className="text-orange-400">+€3.00 / GB EXTRA</span>}
          </div>
        </div>
      </div>
    </div>
  );
}