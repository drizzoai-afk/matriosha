import { createBrowserClient, createServerClient as createSSRServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { createClient as createStandardClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

function requireSupabaseEnv() {
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error("Supabase environment variables are missing.");
  }

  return { supabaseUrl, supabaseAnonKey };
}

export async function createServerClient() {
  const cookieStore = await cookies();
  const env = requireSupabaseEnv();

  return createSSRServerClient(env.supabaseUrl, env.supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
        } catch {
          // no-op for server components
        }
      },
    },
  });
}

export function getSupabaseClient() {
  const env = requireSupabaseEnv();
  return createBrowserClient(env.supabaseUrl, env.supabaseAnonKey);
}

export function getSupabaseStandardClient() {
  const env = requireSupabaseEnv();
  return createStandardClient(env.supabaseUrl, env.supabaseAnonKey);
}
