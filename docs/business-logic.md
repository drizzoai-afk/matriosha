# Matriosha — Business Logic & Monetization Strategy

**Version:** 1.2.0  
**Date:** 2026-04-15  
**Status:** Active

---

## 1. Core Philosophy: "Peace of Mind as a Service"

Matriosha sells **continuity, security, and accessibility**, not just storage. The free tier is fully functional but fragile; the paid tiers provide resilience and scale.

### Value Pillars (The "Why Pay?")
1.  **Key Escrow & Recovery:** Shamir’s Secret Sharing ensures memory survives device loss.
2.  **Multi-Device Sync:** Seamless, encrypted continuity across Mac, PC, and Linux.
3.  **Integrity Monitoring:** Real-time Merkle Root verification with instant alerts on tampering.
4.  **Versioned Backups:** 30-day retention of encrypted snapshots for accidental deletion recovery.

---

## 2. Pricing Tiers

| Feature | Free (Local) | Pro ($9/mo) | Builder ($15/mo) |
| :--- | :---: | :---: | :---: |
| **Storage** | Local Only | 2GB Hot Sync | 10GB Hot Sync |
| **Key Recovery** | ❌ (Self-custody) | ✅ (Shamir's) | ✅ (Shamir's) |
| **Sync** | ❌ | ✅ (Unlimited Devices) | ✅ (Unlimited Devices) |
| **Integrity Alerts** | ❌ | ✅ (Email) | ✅ (Email + SMS) |
| **Backups** | Manual | Auto (30-day) | Auto (90-day) |
| **Cold Storage** | N/A | Auto-Archive >2GB | Auto-Archive >10GB |
| **API Access** | ❌ | ❌ | ✅ (Rate-limited) |

---

## 3. Storage Architecture: Hot vs. Cold (Option C)

To maintain sustainability while offering "perceived unlimited" storage, Matriosha uses a tiered storage strategy.

### 3.1 Hot Storage (Supabase Storage)
*   **Content:** Recent memories, high-importance blocks, and active embeddings.
*   **Performance:** <100ms recall.
*   **Limit:** 2GB (Pro) / 10GB (Builder).
*   **Cost:** ~$0.023/GB/month.

### 3.2 Cold Storage (Cloudflare R2 / S3 Glacier)
*   **Trigger:** When Hot Storage exceeds its limit, the oldest 20% of memories (by timestamp or low importance) are migrated.
*   **Content:** Archived memories, low-importance logs.
*   **Performance:** 2-5s recall (lazy fetch).
*   **Cost:** ~$0.015/GB/month.
*   **User Experience:** Users see all memories in the dashboard. A small "clock" icon indicates a memory is in cold storage and requires a moment to retrieve.

### 3.3 Overage Logic
*   If a Pro user exceeds 2GB of *Hot* storage, auto-archiving begins.
*   If a user wants to keep >2GB in *Hot* storage, they must upgrade to Builder.
*   **Hard Cap:** 100GB total (Hot + Cold). Beyond this, sync pauses until cleanup.

---

## 4. Technical Implementation of Business Logic

### 4.1 Subscription State Machine
```python
class SubscriptionState:
    def __init__(self, user_id):
        self.user_id = user_id
        self.tier = "free"  # free, pro, builder
        self.hot_usage_bytes = 0
        self.cold_usage_bytes = 0

    def check_storage_limit(self, new_block_size):
        limit = 2 * 1024**3 if self.tier == "pro" else 10 * 1024**3
        if self.hot_usage_bytes + new_block_size > limit:
            return "ARCHIVE_OR_UPGRADE"
        return "OK"

    def trigger_archive(self):
        # Move oldest 20% of hot blocks to R2
        pass
```

### 4.2 Stripe Integration Points
*   **`checkout.session.completed`:** Activate Pro/Builder tier, provision Supabase bucket.
*   **`customer.subscription.updated`:** Handle tier changes (e.g., Pro → Builder).
*   **`invoice.payment_failed`:** Grace period (7 days) → Downgrade to Free → Notify user.

---

## 5. Metrics for Success

*   **Conversion Rate:** % of Free users who enable Key Escrow (leading indicator for Pro signup).
*   **Churn Rate:** Target <3% monthly.
*   **Storage Efficiency:** Ratio of Hot vs. Cold storage per user.
*   **Recall Latency:** p95 < 200ms for Hot, < 5s for Cold.

---

**Last Updated:** 2026-04-15 by Nero ⚡
