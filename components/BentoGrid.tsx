"use client";

import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Terminal, ShieldCheck, HardDrive, Zap, Activity, CreditCard } from "lucide-react";
import { useState, useEffect } from "react";

export function BentoGrid() {
  const [status, setStatus] = useState<any>(null);
  const [billing, setBilling] = useState<any>(null);

  useEffect(() => {
    // Fetch real data from our new API endpoints
    Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/billing').then(r => r.json())
    ]).then(([s, b]) => {
      setStatus(s);
      setBilling(b);
    });
  }, []);

  const commands = [
    'matriosha init',
    'matriosha remember "..."',
    'matriosha recall "query"'
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-4 bg-zinc-950 min-h-screen text-white">
      
      {/* Quick Start - Hero */}
      <Card className="md:col-span-2 bg-zinc-900/50 border-zinc-800 col-span-1">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-cyan-400">
            <Terminal className="w-5 h-5" /> Quick Start
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {commands.map((cmd, i) => (
            <div key={i} className="bg-black/40 p-3 rounded font-mono text-sm text-zinc-300 flex justify-between group cursor-pointer hover:text-cyan-300 transition-colors"
                 onClick={() => navigator.clipboard.writeText(cmd)}>
              <span>$ {cmd}</span>
              <span className="opacity-0 group-hover:opacity-100 text-xs text-zinc-500">Copy</span>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Vault Integrity */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-green-400">
            <ShieldCheck className="w-5 h-5" /> Integrity
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="font-mono text-xs break-all text-zinc-400">
            {status?.vault.merkleRoot || "Syncing..."}
          </div>
          <div className="mt-2 text-xs text-zinc-500">Status: {status?.vault.integrity}</div>
        </CardContent>
      </Card>

      {/* MCP Status */}
      <Card className="bg-zinc-900/50 border-zinc-800">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-fuchsia-400">
            <Zap className="w-5 h-5" /> MCP Server
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-sm text-zinc-300">{status?.mcp.status.toUpperCase()}</span>
          </div>
          <div className="text-xs text-zinc-500 mt-1">Port: {status?.mcp.port}</div>
        </CardContent>
      </Card>

      {/* Storage Tiers */}
      <Card className="md:col-span-2 bg-zinc-900/50 border-zinc-800">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white">
            <HardDrive className="w-5 h-5" /> Storage Tiers
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <div className="flex justify-between text-xs mb-1 text-zinc-400">
              <span>Hot (Supabase)</span>
              <span>{(status?.storage.hot.used / 1024**3).toFixed(2)} / 2.00 GB</span>
            </div>
            <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-cyan-500 w-[5%]" />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-xs mb-1 text-zinc-400">
              <span>Cold (R2)</span>
              <span>{(status?.storage.cold.used / 1024**3).toFixed(2)} / 1.00 GB</span>
            </div>
            <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-fuchsia-600 w-[2%]" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Billing & Overage */}
      <Card className="md:col-span-2 bg-zinc-900/50 border-zinc-800">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white">
            <CreditCard className="w-5 h-5" /> Plan & Overage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex justify-between items-center mb-4">
            <div>
              <div className="text-lg font-bold text-white">{billing?.plan}</div>
              <div className="text-xs text-zinc-500">{billing?.price}</div>
            </div>
            <button className="text-xs bg-white text-black px-3 py-1.5 rounded font-medium hover:bg-zinc-200">
              Manage
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-zinc-400 font-mono">
            <div>Hot Overage: <span className="text-zinc-200">{billing?.overage.hot}</span></div>
            <div>Cold Overage: <span className="text-zinc-200">{billing?.overage.cold}</span></div>
          </div>
        </CardContent>
      </Card>

    </div>
  );
}
