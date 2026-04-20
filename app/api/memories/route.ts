import { auth } from "@clerk/nextjs/server";
import { createServerClient } from "@/lib/supabase";
import { NextResponse } from "next/server";

export async function GET() {
  const { userId } = await auth();
  if (!userId) return new NextResponse("Unauthorized", { status: 401 });

  const supabase = await createServerClient();
  
  const { data, error } = await supabase
    .from('memories')
    .select('*')
    .eq('user_id', userId)
    .order('created_at', { ascending: false })
    .limit(50);

  if (error) {
    console.error("Error fetching memories:", error);
    return NextResponse.json({ error: "Failed to fetch memories" }, { status: 500 });
  }

  return NextResponse.json(data);
}

export async function POST(req: Request) {
  const { userId } = await auth();
  if (!userId) return new NextResponse("Unauthorized", { status: 401 });

  const { content, is_hot = true } = await req.json();
  if (!content) return new NextResponse("Content is required", { status: 400 });

  const supabase = await createServerClient();

  // In a real implementation, we would encrypt 'content' here using the user's key
  // For now, we store it as is to validate the flow
  const { data, error } = await supabase
    .from('memories')
    .insert([
      { 
        user_id: userId, 
        content_encrypted: content, 
        is_hot,
        storage_type: is_hot ? 'hot' : 'cold'
      }
    ])
    .select()
    .single();

  if (error) {
    console.error("Error saving memory:", error);
    return NextResponse.json({ error: "Failed to save memory" }, { status: 500 });
  }

  // Update profile storage usage (mock calculation for now)
  await supabase.rpc('increment_storage_usage', { 
    p_user_id: userId, 
    p_bytes: new TextEncoder().encode(content).length 
  });

  return NextResponse.json(data);
}
