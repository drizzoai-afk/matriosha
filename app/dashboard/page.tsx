import { UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { createServerClient } from "@/lib/supabase";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { DashboardActions } from "@/components/dashboard/dashboard-actions";
import { QuickActionsMenu } from "@/components/dashboard/quick-actions-menu";

const GB = 1024 * 1024 * 1024;

type SubscriptionRow = {
  tier: "free" | "pro" | "builder" | null;
  status: "active" | "canceled" | "past_due" | null;
  current_period_end: string | null;
};

type VaultRow = {
  merkle_root: string;
  last_sync: string | null;
};

type EscrowRow = {
  created_at: string | null;
};

export default async function DashboardPage() {
  const { userId } = await auth();
  if (!userId) {
    redirect("/sign-in");
  }

  let subscription: SubscriptionRow | null = null;
  let vault: VaultRow | null = null;
  let escrow: EscrowRow | null = null;
  let vectorCount = 0;
  let supabaseUnavailable = false;

  try {
    const supabase = await createServerClient();

    const [subscriptionResult, vaultResult, escrowResult, vectorsResult] = await Promise.all([
      supabase.from("subscriptions").select("tier,status,current_period_end").eq("user_id", userId).maybeSingle<SubscriptionRow>(),
      supabase.from("vaults").select("merkle_root,last_sync").eq("user_id", userId).maybeSingle<VaultRow>(),
      supabase.from("key_escrow").select("created_at").eq("user_id", userId).maybeSingle<EscrowRow>(),
      supabase.from("memory_vectors").select("id", { count: "exact", head: true }).eq("user_id", userId),
    ]);

    subscription = subscriptionResult.data;
    vault = vaultResult.data;
    escrow = escrowResult.data;
    vectorCount = vectorsResult.count ?? 0;
  } catch (error) {
    supabaseUnavailable = true;
    console.error("Dashboard loaded without Supabase data:", error);
  }

  const normalizedPlan = subscription?.tier ?? "free";
  const planLabel = normalizedPlan === "pro" ? "Standard" : normalizedPlan === "builder" ? "Enterprise" : "Local";
  const subscriptionStatus = subscription?.status ?? "inactive";

  const hotLimit = normalizedPlan === "free" ? 1 * GB : normalizedPlan === "pro" ? 2 * GB : 20 * GB;
  const coldLimit = normalizedPlan === "free" ? 5 * GB : normalizedPlan === "pro" ? 25 * GB : 100 * GB;
  const estimatedHotUsage = Math.max((vectorCount ?? 0) * 4096, 0);
  const estimatedColdUsage = Math.max(Math.floor(estimatedHotUsage * 0.35), 0);

  const hotPct = Math.min((estimatedHotUsage / hotLimit) * 100, 100);
  const coldPct = Math.min((estimatedColdUsage / coldLimit) * 100, 100);

  const periodEnd = subscription?.current_period_end
    ? new Date(subscription.current_period_end).toLocaleDateString("en-GB")
    : "-";

  return (
    <main className="min-h-screen bg-[--bg-base] px-6 py-10 text-foreground md:px-10">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-5">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
            <p className="text-sm text-muted-foreground">Sovereign memory operations and account controls.</p>
          </div>
          <UserButton />
        </header>

        {supabaseUnavailable && (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            Signed in successfully. Dashboard data is limited because Supabase environment variables are not configured.
          </p>
        )}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Card className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">Subscription</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p><span className="text-muted-foreground">Plan:</span> {planLabel}</p>
              <p><span className="text-muted-foreground">Status:</span> {subscriptionStatus}</p>
              <p><span className="text-muted-foreground">Billing ends:</span> {periodEnd}</p>
              <DashboardActions mode="billing" />
            </CardContent>
          </Card>

          <Card className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">Storage Usage</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="space-y-1">
                <div className="flex justify-between text-muted-foreground"><span>Hot</span><span>{hotPct.toFixed(1)}%</span></div>
                <Progress value={hotPct} className="[&_[data-slot=progress-indicator]]:bg-cyan-400" />
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-muted-foreground"><span>Cold</span><span>{coldPct.toFixed(1)}%</span></div>
                <Progress value={coldPct} className="[&_[data-slot=progress-indicator]]:bg-fuchsia-400" />
              </div>
              <p className="text-xs text-muted-foreground">Overages: hot €6/GB/mo · cold €3/GB/mo</p>
            </CardContent>
          </Card>

          <Card className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">Vault Integrity</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p className="break-all text-xs text-muted-foreground">{vault?.merkle_root ?? "No Merkle root yet"}</p>
              <p><span className="text-muted-foreground">Last sync:</span> {vault?.last_sync ? new Date(vault.last_sync).toLocaleString("en-GB") : "-"}</p>
              <DashboardActions mode="verify" />
            </CardContent>
          </Card>

          <Card className="border-border bg-card/70 md:col-span-2 xl:col-span-1">
            <CardHeader>
              <CardTitle className="text-base">Hot Storage</CardTitle>
            </CardHeader>
            <CardContent>
              <DashboardActions mode="memory" />
            </CardContent>
          </Card>

          <Card className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">Cold Storage</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="text-muted-foreground">Archive a memory into cold tier.</p>
              <DashboardActions mode="archive" />
            </CardContent>
          </Card>

          <Card className="border-border bg-card/70">
            <CardHeader>
              <CardTitle className="text-base">Key Recovery</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p><span className="text-muted-foreground">Escrow:</span> {escrow ? "Configured" : "Not configured"}</p>
              <p><span className="text-muted-foreground">Updated:</span> {escrow?.created_at ? new Date(escrow.created_at).toLocaleString("en-GB") : "-"}</p>
              <div className="flex flex-wrap gap-2 pt-1">
                <DashboardActions mode="test-recovery" />
                <DashboardActions mode="configure-recovery" />
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="border-border bg-card/70">
          <CardHeader>
            <CardTitle className="text-base">Quick Actions</CardTitle>
          </CardHeader>
          <CardContent>
            <QuickActionsMenu />
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
