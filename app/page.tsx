import { BentoGrid } from "../components/BentoGrid";
import { SignInButton, UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { ShieldCheck } from "lucide-react";

export default async function DashboardPage() {
  const { userId } = await auth();

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <header className="border-b border-zinc-800 p-4 flex justify-between items-center sticky top-0 bg-zinc-950/80 backdrop-blur z-10">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-6 h-6 text-cyan-500" />
          <h1 className="font-bold tracking-tight">Matriosha <span className="text-zinc-600 font-mono text-xs">v1.3.0</span></h1>
        </div>
        <div>
          {!userId ? (
            <SignInButton mode="modal">
              <button className="bg-white text-black px-4 py-1.5 rounded text-sm font-medium hover:bg-zinc-200 transition">Sign In</button>
            </SignInButton>
          ) : (
            <UserButton />
          )}
        </div>
      </header>
      <BentoGrid />
    </div>
  );
}
