"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ShieldCheck, AlertTriangle } from "lucide-react";

export function VaultIntegrityCard() {
  // In production, this would fetch from Supabase via a server action or API route
  const isHealthy = true; 
  const lastSync = "2 minutes ago";

  return (
    <Card className="bg-zinc-900/50 border-zinc-800 text-white">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-zinc-100">
          <ShieldCheck className={`w-5 h-5 ${isHealthy ? 'text-green-500' : 'text-red-500'}`} />
          Vault Integrity
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <span className="text-zinc-400">Merkle Root Status</span>
            <span className={`font-mono text-sm ${isHealthy ? 'text-green-400' : 'text-red-400'}`}>
              {isHealthy ? "VERIFIED" : "MISMATCH"}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-zinc-400">Last Sync</span>
            <span className="font-mono text-sm text-zinc-200">{lastSync}</span>
          </div>
          {!isHealthy && (
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
