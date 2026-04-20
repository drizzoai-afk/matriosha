import { UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { createServerClient } from "@/lib/supabase";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Shield, Database, Activity, Plus, Archive } from "lucide-react";

export default async function Dashboard() {
  const { userId } = await auth();
  if (!userId) return null; // Should be protected by middleware

  const supabase = await createServerClient();
  
  // Fetch user profile and subscription status
  const { data: profile } = await supabase
    .from('profiles')
    .select('*')
    .eq('id', userId)
    .single();

  const { data: subscription } = await supabase
    .from('subscriptions')
    .select('*')
    .eq('user_id', userId)
    .maybeSingle();

  const planName = subscription?.plan || 'Local';
  const isActive = subscription?.status === 'active';
  const storageUsedMB = (profile?.storage_used_bytes || 0) / (1024 * 1024);
  const storageLimitMB = planName === 'Standard' ? 5120 : 500; // 5GB for Standard, 500MB for Local
  const storagePercent = Math.min((storageUsedMB / storageLimitMB) * 100, 100);

  return (
    <main className="min-h-screen p-8 md:p-24 bg-[#080808]">
      <div className="max-w-6xl mx-auto space-y-8">
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-800 pb-6">
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Dashboard</h1>
            <p className="text-zinc-400 mt-1">Manage your sovereign memory vaults.</p>
          </div>
          <div className="flex items-center gap-4">
            <div className={`px-3 py-1.5 rounded-full border text-xs font-mono font-medium ${isActive ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : 'border-zinc-700 bg-zinc-900 text-zinc-500'}`}>
              {planName.toUpperCase()} {isActive ? 'ACTIVE' : 'INACTIVE'}
            </div>
            <UserButton />
          </div>
        </header>
        
        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Storage Card */}
          <Card className="bg-zinc-900/50 border-zinc-800 col-span-1 md:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-mono text-cyan-400 flex items-center gap-2">
                <Database className="w-4 h-4" /> STORAGE USAGE
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex justify-between items-end mb-2">
                <span className="text-2xl font-bold text-white">{storageUsedMB.toFixed(1)} MB</span>
                <span className="text-sm text-zinc-500 font-mono">/ {storageLimitMB >= 1024 ? (storageLimitMB/1024).toFixed(0) + ' GB' : storageLimitMB + ' MB'}</span>
              </div>
              <Progress value={storagePercent} className="h-2 bg-zinc-800 [&>div]:bg-cyan-500" />
              <p className="text-xs text-zinc-500 mt-3 text-right">{storagePercent.toFixed(1)}% utilized</p>
            </CardContent>
          </Card>

          {/* Vault Integrity Card */}
          <Card className="bg-zinc-900/50 border-zinc-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-mono text-fuchsia-400 flex items-center gap-2">
                <Shield className="w-4 h-4" /> VAULT INTEGRITY
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between mt-2">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-full bg-emerald-500/10 flex items-center justify-center border border-emerald-500/20">
                    <Shield className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <p className="text-lg font-semibold text-white">Verified</p>
                    <p className="text-xs text-zinc-500 font-mono">Merkle root matches</p>
                  </div>
                </div>
                <Button variant="ghost" size="sm" className="text-xs text-zinc-400 hover:text-white">
                  Re-verify
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Hot Storage Interface */}
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardHeader>
            <CardTitle className="text-sm font-mono text-zinc-300 flex items-center gap-2">
              <Plus className="w-4 h-4" /> NEW MEMORY (HOT STORAGE)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <textarea 
              placeholder="What should I remember for you?"
              className="w-full h-32 bg-black/30 border border-zinc-700 rounded-md p-4 text-sm text-white focus:outline-none focus:border-cyan-500 transition-colors resize-none"
            />
            <div className="flex justify-end">
              <Button className="bg-cyan-600 hover:bg-cyan-700 text-white">
                Encrypt & Save to Vault
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Recent Activity List */}
        <Card className="bg-zinc-900/50 border-zinc-800">
          <CardHeader>
            <CardTitle className="text-sm font-mono text-zinc-300 flex items-center gap-2">
              <Activity className="w-4 h-4" /> RECENT ACTIVITY
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-center py-12 text-zinc-500 text-sm">
              No recent memory operations found.
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
