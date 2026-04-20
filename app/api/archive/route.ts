import { auth } from "@clerk/nextjs/server";
import { createServerClient } from "@/lib/supabase";
import { NextResponse } from "next/server";

// In a real implementation, we would use the R2 SDK here.
// For now, we simulate the archiving process by updating the DB status.
export async function POST(req: Request) {
  const { userId } = await auth();
  if (!userId) return new NextResponse("Unauthorized", { status: 401 });

  const { memoryId } = await req.json();
  if (!memoryId) return new NextResponse("Memory ID is required", { status: 400 });

  const supabase = await createServerClient();

  // 1. Update status to 'cold' in Supabase
  const { error: updateError } = await supabase
    .from('memories')
    .update({ storage_type: 'cold', is_hot: false })
    .eq('id', memoryId)
    .eq('user_id', userId); // Ensure ownership

  if (updateError) {
    console.error("Error archiving memory:", updateError);
    return NextResponse.json({ error: "Failed to archive memory" }, { status: 500 });
  }

  // 2. TODO: Upload encrypted blob to Cloudflare R2 here using AWS SDK
  // 3. TODO: Delete hot storage content from Supabase to save space

  return NextResponse.json({ success: true, message: "Memory archived to cold storage" });
}
