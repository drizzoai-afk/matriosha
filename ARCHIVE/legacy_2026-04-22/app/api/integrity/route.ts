import { auth } from "@clerk/nextjs/server";
import { createServerClient } from "@/lib/supabase";
import { NextResponse } from "next/server";

// Mock Merkle Root calculation for validation
// In production, this would use the Python core logic to hash all blocks
const calculateMockMerkleRoot = (userId: string) => {
  return `0x${Buffer.from(userId + Date.now()).toString('hex').substring(0, 64)}`;
};

export async function GET() {
  const { userId } = await auth();
  if (!userId) return new NextResponse("Unauthorized", { status: 401 });

  const supabase = await createServerClient();

  // 1. Fetch the stored Merkle root from the user's profile or vault config
  const { data: profile } = await supabase
    .from('profiles')
    .select('merkle_root')
    .eq('id', userId)
    .single();

  // 2. Calculate current root (mocked for now)
  const currentRoot = calculateMockMerkleRoot(userId);
  
  // 3. Compare
  const isIntact = profile?.merkle_root === currentRoot || !profile?.merkle_root; // Assume valid if no root yet

  return NextResponse.json({
    status: isIntact ? 'verified' : 'tampered',
    current_root: currentRoot,
    stored_root: profile?.merkle_root
  });
}

export async function POST(req: Request) {
  const { userId } = await auth();
  if (!userId) return new NextResponse("Unauthorized", { status: 401 });

  const supabase = await createServerClient();
  const newRoot = calculateMockMerkleRoot(userId);

  // Update the stored root after a successful write operation
  const { error } = await supabase
    .from('profiles')
    .update({ merkle_root: newRoot })
    .eq('id', userId);

  if (error) {
    return NextResponse.json({ error: "Failed to update integrity hash" }, { status: 500 });
  }

  return NextResponse.json({ status: 'updated', root: newRoot });
}
