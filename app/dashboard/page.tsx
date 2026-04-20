import { UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { createServerClient } from "@/lib/supabase";

export default async function Dashboard() {
  const { userId } = await auth();
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
  const statusColor = subscription?.status === 'active' ? 'text-emerald-400' : 'text-zinc-500';

  return (
    <main className="min-h-screen p-24 bg-[#080808]">
      <div className="max-w-5xl mx-auto">
        <header className="flex justify-between items-center mb-12 border-b border-zinc-800 pb-6">
          <h1 className="text-3xl font-bold text-cyan-400">Dashboard</h1>
          <UserButton />
        </header>
        
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-8">
          <div className="flex justify-between items-start mb-6">
            <div>
              <h2 className="text-xl font-semibold text-white">Welcome back, Agent.</h2>
              <p className="text-zinc-400">Your sovereign memory layer is active.</p>
            </div>
            <div className={`px-3 py-1 rounded-full border border-zinc-700 text-xs font-mono ${statusColor}`}>
              {planName.toUpperCase()} PLAN
            </div>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-md">
              <h3 className="font-mono text-sm text-cyan-500 mb-2">STORAGE USED</h3>
              <p className="text-lg">{(profile?.storage_used_bytes || 0 / 1024 / 1024).toFixed(2)} MB</p>
            </div>
            <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-md">
              <h3 className="font-mono text-sm text-fuchsia-500 mb-2">VAULT STATUS</h3>
              <p className="text-lg">Initialized</p>
            </div>
            <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-md">
              <h3 className="font-mono text-sm text-emerald-500 mb-2">INTEGRITY</h3>
              <p className="text-lg">Verified</p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
