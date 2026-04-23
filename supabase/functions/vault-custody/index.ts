import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") ?? "";

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  throw new Error("SUPABASE_URL and SUPABASE_ANON_KEY are required for vault-custody edge function");
}

type CustodyRequest = {
  action: "upsert" | "fetch" | "seal" | "unseal";
  wrapped_key_b64?: string;
  kdf_salt_b64?: string;
  algo?: string;
  plaintext_b64?: string;
  sealed_b64?: string;
};

function json(status: number, payload: Record<string, unknown>) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return json(405, { error: "method_not_allowed" });
  }

  const authHeader = req.headers.get("Authorization");
  if (!authHeader?.startsWith("Bearer ")) {
    return json(401, { error: "missing_bearer_token" });
  }

  let body: CustodyRequest;
  try {
    body = (await req.json()) as CustodyRequest;
  } catch (_err) {
    return json(400, { error: "invalid_json" });
  }

  const client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: authHeader } },
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: userData, error: userError } = await client.auth.getUser();
  if (userError || !userData.user) {
    console.error("vault-custody auth failure", { reason: userError?.message ?? "user_missing" });
    return json(401, { error: "unauthorized" });
  }

  const userId = userData.user.id;

  try {
    if (body.action === "upsert") {
      if (!body.wrapped_key_b64 || !body.kdf_salt_b64) {
        return json(400, { error: "missing_wrapped_key_material" });
      }

      const { error } = await client.from("vault_keys").upsert(
        {
          user_id: userId,
          wrapped_key: body.wrapped_key_b64,
          kdf_salt: body.kdf_salt_b64,
          algo: body.algo ?? "aes-gcm",
          rotated_at: new Date().toISOString(),
        },
        { onConflict: "user_id" },
      );

      if (error) {
        console.error("vault-custody upsert failed", { code: error.code, action: "upsert" });
        return json(500, { error: "upsert_failed" });
      }

      return json(200, { status: "ok" });
    }

    if (body.action === "fetch") {
      const { data, error } = await client
        .from("vault_keys")
        .select("kdf_salt, wrapped_key, algo, rotated_at")
        .eq("user_id", userId)
        .single();

      if (error) {
        console.error("vault-custody fetch failed", { code: error.code, action: "fetch" });
        return json(404, { error: "wrapped_key_not_found" });
      }

      return json(200, {
        kdf_salt_b64: data.kdf_salt,
        wrapped_key_b64: data.wrapped_key,
        algo: data.algo,
        rotated_at: data.rotated_at,
      });
    }

    if (body.action === "seal") {
      if (!body.plaintext_b64) {
        return json(400, { error: "missing_plaintext_b64" });
      }

      const { data, error } = await client.rpc("vault_seal_box", {
        plaintext_b64: body.plaintext_b64,
      });
      if (error) {
        console.error("vault-custody seal RPC failed", { code: error.code, action: "seal" });
        return json(500, { error: "seal_rpc_failed" });
      }

      return json(200, { sealed_b64: data });
    }

    if (body.action === "unseal") {
      if (!body.sealed_b64) {
        return json(400, { error: "missing_sealed_b64" });
      }

      const { data, error } = await client.rpc("vault_open_box", {
        sealed_b64: body.sealed_b64,
      });
      if (error) {
        console.error("vault-custody unseal RPC failed", { code: error.code, action: "unseal" });
        return json(500, { error: "unseal_rpc_failed" });
      }

      return json(200, { plaintext_b64: data });
    }

    return json(400, { error: "unknown_action" });
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown_error";
    console.error("vault-custody unexpected failure", { reason: message });
    return json(500, { error: "internal_error" });
  }
});
