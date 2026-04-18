"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ShieldCheck, AlertTriangle, Loader2 } from "lucide-react";
import { createBrowserClient } from "@supabase/ssr";

export function VaultIntegrityCard() {
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [lastSync, setLastSync] = useState<string>("Loading...");
  
  const supabase = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  useEffect(() => {
    const checkIntegrity = async () => {
      try {
        const { data, error } = await supabase
          .from('vault_status')
          .select('is_healthy, last_sync')
          .single();

        if (error) throw error;

        setIsHealthy(data.is_healthy);
        setLastSync(new Date(data.last_sync).toLocaleString());
      } catch (err) {
        console.error("Failed to fetch vault status:", err);
        setIsHealthy(false);
        setLastSync("Error");
      }
    };

    checkIntegrity();
  }, []);

  return (
    <Card className="bg-zinc-900/50 border-zinc-800 text-white">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-zinc-100">
          <ShieldCheck className={`w-5 h-5 ${isHealthy ? 'text-green-500' : isHealthy === false ? 'text-red-500' : 'text-zinc-500'}`} />
          Vault Integrity
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-zinc-400">Merkle Root Status</span>
            {isHealthy === null ? (
              <Loader2 className="w-4 h-4 animate-spin text-zinc-500" />
            ) : (
              <span className={`font-mono text-sm ${isHealthy ? 'text-green-400' : 'text-red-400'}`}>
                {isHealthy ? "VERIFIED" : "MISMATCH"}
              </span>
            )}
          </div>
          <div className="flex justify-between items-center">
            <span className="text-zinc-400">Last Sync</span>
            <span className="font-mono text-sm text-zinc-200">{lastSync}</span>
          </div>
          {!isHealthy && isHealthy !== null && (
            <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-md flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5" />
              <p className="text-xs text-red-200">Integrity check failed. Please re-sync your vault.</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}