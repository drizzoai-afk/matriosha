"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

type ActionMode = "verify" | "memory" | "archive" | "billing" | "test-recovery" | "configure-recovery";

interface DashboardActionsProps {
  mode: ActionMode;
}

async function safeJson(response: Response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export function DashboardActions({ mode }: DashboardActionsProps) {
  const [content, setContent] = useState("");
  const [memoryId, setMemoryId] = useState("");
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [loading, setLoading] = useState(false);

  if (mode === "billing") {
    return (
      <Button
        className="mt-2 bg-cyan-500 text-black hover:bg-cyan-400"
        onClick={async () => {
          setLoading(true);
          setStatusMessage("");
          try {
            const response = await fetch("/api/billing", { method: "GET" });
            const payload = await safeJson(response);
            if (!response.ok) throw new Error(payload?.error ?? "Unable to load billing portal");
            if (payload?.stripePortalUrl) {
              window.location.href = payload.stripePortalUrl;
              return;
            }
            throw new Error("No billing portal URL configured.");
          } catch (error) {
            setStatusMessage(error instanceof Error ? error.message : "Billing request failed");
          } finally {
            setLoading(false);
          }
        }}
      >
        {loading ? "Loading..." : "Manage Billing"}
      </Button>
    );
  }

  if (mode === "verify") {
    return (
      <div className="space-y-2">
        <Button
          variant="outline"
          onClick={async () => {
            setLoading(true);
            setStatusMessage("");
            try {
              const response = await fetch("/api/integrity", { method: "GET" });
              const payload = await safeJson(response);
              if (!response.ok) throw new Error(payload?.error ?? "Integrity check failed");
              setStatusMessage(`Integrity status: ${payload?.status ?? "unknown"}`);
            } catch (error) {
              setStatusMessage(error instanceof Error ? error.message : "Integrity request failed");
            } finally {
              setLoading(false);
            }
          }}
        >
          {loading ? "Verifying..." : "Verify Now"}
        </Button>
        {statusMessage ? <p className="text-xs text-muted-foreground">{statusMessage}</p> : null}
      </div>
    );
  }

  if (mode === "memory") {
    return (
      <div className="space-y-3">
        <Textarea
          placeholder="Enter memory payload"
          value={content}
          onChange={(event) => setContent(event.target.value)}
          className="min-h-28"
        />
        <Button
          className="bg-cyan-500 text-black hover:bg-cyan-400"
          disabled={!content.trim() || loading}
          onClick={async () => {
            setLoading(true);
            setStatusMessage("");
            try {
              const response = await fetch("/api/memories", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content, is_hot: true }),
              });
              const payload = await safeJson(response);
              if (!response.ok) throw new Error(payload?.error ?? "Memory save failed");
              setStatusMessage("Encrypted payload saved to hot storage.");
              setMemoryId(payload?.id ?? memoryId);
              setContent("");
            } catch (error) {
              setStatusMessage(error instanceof Error ? error.message : "Memory request failed");
            } finally {
              setLoading(false);
            }
          }}
        >
          {loading ? "Saving..." : "Encrypt & Save"}
        </Button>
        {memoryId ? <p className="text-xs text-muted-foreground">Last memory ID: {memoryId}</p> : null}
        {statusMessage ? <p className="text-xs text-muted-foreground">{statusMessage}</p> : null}
      </div>
    );
  }

  if (mode === "archive") {
    return (
      <div className="space-y-3">
        <Textarea
          placeholder="Memory ID to archive"
          value={memoryId}
          onChange={(event) => setMemoryId(event.target.value)}
          className="min-h-16"
        />
        <Button
          variant="outline"
          disabled={!memoryId.trim() || loading}
          onClick={async () => {
            setLoading(true);
            setStatusMessage("");
            try {
              const response = await fetch("/api/archive", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ memoryId }),
              });
              const payload = await safeJson(response);
              if (!response.ok) throw new Error(payload?.error ?? "Archive failed");
              setStatusMessage("Archive request completed.");
            } catch (error) {
              setStatusMessage(error instanceof Error ? error.message : "Archive request failed");
            } finally {
              setLoading(false);
            }
          }}
        >
          {loading ? "Archiving..." : "Archive"}
        </Button>
        {statusMessage ? <p className="text-xs text-muted-foreground">{statusMessage}</p> : null}
      </div>
    );
  }

  if (mode === "test-recovery") {
    return <Button variant="outline">Test Recovery</Button>;
  }

  return (
    <Link href="mailto:drizzo.ai@gmail.com">
      <Button variant="outline">Configure Recovery</Button>
    </Link>
  );
}
