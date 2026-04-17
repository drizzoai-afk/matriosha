#!/usr/bin/env bash
# ============================================================
# Matriosha — Push All Secrets to GCP + genera .env locale
# ============================================================
# PREREQUISITI:
#   - gcloud auth login (già fatto)
#   - gcloud config set project matriosha (già fatto)
#
# USO:
#   1. Riempi i valori sotto (tra le virgolette)
#   2. chmod +x scripts/push-secrets.sh
#   3. ./scripts/push-secrets.sh
#   4. CANCELLA QUESTO FILE: rm scripts/push-secrets.sh
#
# ⚠️  NON COMMITTARE MAI QUESTO FILE CON I VALORI REALI
# ============================================================

set -euo pipefail

# ── RIEMPI QUI ──────────────────────────────────────────────
SUPABASE_URL=""
SUPABASE_ANON_KEY=""
SUPABASE_SERVICE_ROLE_KEY=""
CLERK_SECRET_KEY=""
CLERK_PUBLISHABLE_KEY=""
STRIPE_SECRET_KEY=""
STRIPE_WEBHOOK_SECRET=""
STRIPE_PRO_PRICE_ID=""
PLATFORM_MASTER_KEY=""
R2_ACCESS_KEY_ID=""
R2_SECRET_ACCESS_KEY=""
# ────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "🪆 Matriosha — Secret Push (GCP + .env)"
echo "========================================"
echo ""

# Controlla valori
MISSING=0
for VAR in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY \
           CLERK_SECRET_KEY CLERK_PUBLISHABLE_KEY \
           STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRO_PRICE_ID \
           PLATFORM_MASTER_KEY R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
    if [ -z "${!VAR}" ]; then
        echo -e "${RED}✗ $VAR è vuoto${NC}"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo -e "\n${RED}Riempi tutti i valori prima di lanciare.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Tutti i valori presenti${NC}\n"

# ── 1. GCP SECRET MANAGER ──────────────────────────────────
echo -e "${YELLOW}▸ GCP Secret Manager...${NC}"

for VAR in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY \
           CLERK_SECRET_KEY CLERK_PUBLISHABLE_KEY \
           STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRO_PRICE_ID \
           PLATFORM_MASTER_KEY R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
    # Aggiorna se esiste, crea se no
    if gcloud secrets describe "$VAR" &>/dev/null; then
        echo -n "${!VAR}" | gcloud secrets versions add "$VAR" --data-file=- 2>/dev/null && \
            echo -e "  ${GREEN}↻ $VAR (nuova versione)${NC}" || \
            echo -e "  ${RED}✗ $VAR${NC}"
    else
        echo -n "${!VAR}" | gcloud secrets create "$VAR" --data-file=- 2>/dev/null && \
            echo -e "  ${GREEN}✓ $VAR (creato)${NC}" || \
            echo -e "  ${RED}✗ $VAR${NC}"
    fi
done

echo ""

# ── 2. .ENV LOCALE ─────────────────────────────────────────
echo -e "${YELLOW}▸ Generazione .env locale...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cat > "$PROJECT_DIR/.env" <<EOF
# Matriosha — Local Dev Environment
# Generato da push-secrets.sh — NON COMMITTARE

SUPABASE_URL=$SUPABASE_URL
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_SERVICE_ROLE_KEY
CLERK_SECRET_KEY=$CLERK_SECRET_KEY
CLERK_PUBLISHABLE_KEY=$CLERK_PUBLISHABLE_KEY
STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_SECRET
STRIPE_PRO_PRICE_ID=$STRIPE_PRO_PRICE_ID
PLATFORM_MASTER_KEY=$PLATFORM_MASTER_KEY
R2_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY
GCP_PROJECT=matriosha
EOF

echo -e "  ${GREEN}✓ .env${NC}"

# ── 3. DASHBOARD .ENV.LOCAL ─────────────────────────────────
cat > "$PROJECT_DIR/dashboard/.env.local" <<EOF
# Matriosha Dashboard — Local Dev
# Generato da push-secrets.sh — NON COMMITTARE

NEXT_PUBLIC_SUPABASE_URL=$SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$CLERK_PUBLISHABLE_KEY
CLERK_SECRET_KEY=$CLERK_SECRET_KEY
STRIPE_SECRET_KEY=$STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK_SECRET
EOF

echo -e "  ${GREEN}✓ dashboard/.env.local${NC}"

# ── 4. .GITIGNORE ──────────────────────────────────────────
echo ""
for PATTERN in ".env" ".env.local" "push-secrets.sh" "gcp-sa-key.json"; do
    if ! grep -qF "$PATTERN" "$PROJECT_DIR/.gitignore" 2>/dev/null; then
        echo "$PATTERN" >> "$PROJECT_DIR/.gitignore"
        echo -e "  ${YELLOW}+ $PATTERN aggiunto a .gitignore${NC}"
    fi
done

# ── DONE ────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
echo -e "${GREEN}✓ FATTO! 11 secrets su GCP + .env locali${NC}"
echo ""
echo -e "${RED}⚠️  ORA CANCELLA QUESTO FILE:${NC}"
echo -e "${RED}   rm $0${NC}"
echo "════════════════════════════════════════════"
