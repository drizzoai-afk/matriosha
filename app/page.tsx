import { SignInButton, SignUpButton, SignedIn, SignedOut } from "@clerk/nextjs";

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-24 bg-[#080808]">
      <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm lg:flex">
        <h1 className="text-4xl font-bold mb-8 text-cyan-400">Matriosha</h1>
        
        <SignedOut>
          <div className="flex gap-4">
            <SignInButton mode="modal">
              <button className="px-6 py-2 border border-zinc-700 rounded-md hover:bg-zinc-900 transition-colors">
                Log In
              </button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="px-6 py-2 bg-cyan-600 text-white rounded-md hover:bg-cyan-700 transition-colors">
                Sign Up
              </button>
            </SignUpButton>
          </div>
        </SignedOut>

        <SignedIn>
          <a href="/dashboard" className="px-6 py-2 bg-cyan-600 text-white rounded-md hover:bg-cyan-700 transition-colors">
            Go to Dashboard
          </a>
        </SignedIn>
      </div>
    </main>
  );
}
