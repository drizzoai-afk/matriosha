"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HardDrive, Archive } from "lucide-react";

export function StorageTierVisualizer() {
  // Mock data for visualization
  const hotUsage = 1.2; // GB
  const hotLimit = 2.0; // GB
  const coldUsage = 0.5; // GB
  
  const hotPercentage = (hotUsage / hotLimit) * 100;

  return (
    <Card className="bg-zinc-900/50 border-zinc-800 text-white">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-zinc-100">
          <HardDrive className="w-5 h-5 text-cyan-500" />
          Storage Tiers
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          {/* Hot Storage */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-zinc-400 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-cyan-500" />
                Hot Storage (Supabase)
              </span>
              <span className="font-mono text-zinc-200">{hotUsage.toFixed(1)} / {hotLimit.toFixed(1)} GB</span>
            </div>
            <div className="h-2 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-cyan-500 transition-all" style={{ width: `${hotPercentage}%` }} />
            </div>
          </div>

          {/* Cold Storage */}
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-zinc-400 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-magenta-500" />
                Cold Storage (R2)
              </span>
              <span className="font-mono text-zinc-200">{coldUsage.toFixed(1)} GB</span>
            </div>
            <div className="h-2 w-full bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-fuchsia-600 w-[25%]" />
            </div>
          </div>

          <div className="pt-2 border-t border-zinc-800">
            <p className="text-xs text-zinc-500">
              Auto-archiving is active. Memories older than 30 days are moved to Cold Storage.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
