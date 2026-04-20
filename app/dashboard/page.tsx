import { UserButton, auth } from "@clerk/nextjs";

export default function Dashboard() {
  const { userId } = auth();

  return (
    <main className="min-h-screen p-24 bg-[#080808]">
      <div className="max-w-5xl mx-auto">
        <header className="flex justify-between items-center mb-12 border-b border-zinc-800 pb-6">
          <h1 className="text-3xl font-bold text-cyan-400">Dashboard</h1>
          <UserButton />
        </header>
        
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-8">
          <h2 className="text-xl font-semibold mb-4">Welcome, Agent.</h2>
          <p className="text-zinc-400 mb-6">Your sovereign memory layer is active.</p>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-md">
              <h3 className="font-mono text-sm text-cyan-500 mb-2">STATUS</h3>
              <p className="text-lg">Active</p>
            </div>
            <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-md">
              <h3 className="font-mono text-sm text-fuchsia-500 mb-2">USER ID</h3>
              <p className="text-lg font-mono text-xs break-all">{userId}</p>
            </div>
            <div className="p-6 bg-zinc-900 border border-zinc-800 rounded-md">
              <h3 className="font-mono text-sm text-emerald-500 mb-2">ENCRYPTION</h3>
              <p className="text-lg">AES-256-GCM</p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
