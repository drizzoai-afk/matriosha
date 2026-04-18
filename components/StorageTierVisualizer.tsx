"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HardDrive, Database, Cloud, Loader2, AlertCircle } from "lucide-react";
import { createBrowserClient } from "@supabase/ssr";

// Costanti dalla SPEC.md (Sezione 8.1)
const HOT_LIMIT_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB
const COLD_LIMIT_BYTES = 1 * 1024 * 1024 * 1024; // 1 GB

export function StorageTierVisualizer() {
  const [usage, setUsage] = useState<{ hot: number; cold: number; overageCost: string } | null>(null);
  
  const supabase = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  useEffect(() => {
    const fetchBillingStatus = async () => {
      try {
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
  }, []);

  const hotGB = usage ? (usage.hot / 1024).toFixed(2) : "0.00";
  const coldGB = usage ? (usage.cold / 1024).toFixed(2) : "0.00";
  
  const isHotOver = usage && (usage.hot * 1024 * 1024) > HOT_LIMIT_BYTES;
  const isColdOver = usage && (usage.cold * 1024 * 1024) > COLD_LIMIT_BYTES;

  return (
    <Card className="bg-zinc-900/50 border-zinc-800 text-white">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-zinc-100">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-fuchsia-500" />
            Storage Tiers
          </div>
          {usage && parseFloat(usage.overageCost) > 0 && (
            <div className="flex items-center gap-2 px-2 py-1 rounded-full bg-orange-500/10 border border-orange-500/20 text-orange-400 text-[10px] font-mono">
              <AlertCircle className="w-3 h-3" />
              Overage: €{usage.overageCost}/mo
            </div>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Hot Storage */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-zinc-400 flex items-center gap-2">
                <HardDrive className={`w-4 h-4 ${isHotOver ? 'text-orange-400' : 'text-cyan-400'}`} /> 
                Hot Storage (Supabase)
              </span>
              <span className={`font-mono ${isHotOver ? 'text-orange-400' : 'text-cyan-400'}`}>
                {hotGB} GB
              </span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div 
                className={`h-full transition-all duration-500 ${isHotOver ? 'bg-orange-500' : 'bg-cyan-500'}`} 
                style={{ width: usage ? `${Math.min(((usage.hot * 1024 * 1024) / HOT_LIMIT_BYTES) * 100, 100)}%` : '0%' }} 
              />
            </div>
            <p className="text-xs text-zinc-500">2 GB Limit • Auto-archive to Cold after 30 days</p>
          </div>

          {/* Cold Storage */}
          <div className="space-y-2 pt-4 border-t border-zinc-800">
            <div className="flex justify-between text-sm">
              <span className="text-zinc-400 flex items-center gap-2">
                <Cloud className={`w-4 h-4 ${isColdOver ? 'text-orange-400' : 'text-fuchsia-400'}`} /> 
                Cold Storage (R2)
              </span>
              <span className={`font-mono ${isColdOver ? 'text-orange-400' : 'text-fuchsia-400'}`}>
                {coldGB} GB
              </span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div 
                className={`h-full transition-all duration-500 ${isColdOver ? 'bg-orange-500' : 'bg-fuchsia-500'}`} 
                style={{ width: usage ? `${Math.min(((usage.cold * 1024 * 1024) / COLD_LIMIT_BYTES) * 100, 100)}%` : '0%' }} 
              />
            </div>
            <p className="text-xs text-zinc-500">1 GB Included • Encrypted & Archived</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}