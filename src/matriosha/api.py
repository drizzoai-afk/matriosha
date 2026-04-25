from fastapi import FastAPI, Header, HTTPException, Depends
import os

app = FastAPI()


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_DIAGNOSTICS_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="admin diagnostics token not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=404, detail="not found")


@app.get("/")
def read_root():
    return {"status": "Matriosha API is running"}


@app.get("/health/secrets")
def health_secrets(_: None = Depends(require_admin_token)):
    names = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_JWT_SECRET",
        "SUPABASE_PASSWORD",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "GCP_PROJECT_ID",
        "ADMIN_DIAGNOSTICS_TOKEN",
    ]

    return {
        "status": "ok",
        "env": {
            name: {
                "present": bool(os.getenv(name)),
                "length": len(os.getenv(name, "")),
            }
            for name in names
        },
    }


@app.get("/health/deps")
def health_deps(_: None = Depends(require_admin_token)):
    deps = {}
    for name in ["supabase", "stripe", "httpx"]:
        try:
            __import__(name)
            deps[name] = {"available": True}
        except Exception as exc:
            deps[name] = {
                "available": False,
                "error": exc.__class__.__name__,
            }

    return {"status": "ok", "deps": deps}


@app.get("/health/supabase")
def health_supabase(_: None = Depends(require_admin_token)):
    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        if not url or not key:
            return {"status": "error", "provider": "supabase", "error": "missing_env"}

        client = create_client(url, key)
        result = client.auth.admin.list_users(page=1, per_page=1)

        return {
            "status": "ok",
            "provider": "supabase",
            "result_type": type(result).__name__,
        }

    except Exception as exc:
        return {
            "status": "error",
            "provider": "supabase",
            "error": exc.__class__.__name__,
            "message": str(exc)[:300],
        }


@app.get("/health/stripe")
def health_stripe(_: None = Depends(require_admin_token)):
    try:
        import httpx

        key = os.getenv("STRIPE_SECRET_KEY")
        if not key:
            return {"status": "error", "provider": "stripe", "error": "missing_env"}

        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://api.stripe.com/v1/account",
                headers={"Authorization": f"Bearer {key}"},
            )

        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = {}
            err = data.get("error", {}) if isinstance(data, dict) else {}
            return {
                "status": "error",
                "provider": "stripe",
                "http_status": response.status_code,
                "stripe_error_type": err.get("type"),
                "stripe_error_code": err.get("code"),
                "message": str(err.get("message") or response.text)[:300],
            }

        data = response.json()
        return {
            "status": "ok",
            "provider": "stripe",
            "account_id": data.get("id"),
            "livemode": data.get("livemode"),
            "charges_enabled": data.get("charges_enabled"),
            "payouts_enabled": data.get("payouts_enabled"),
        }

    except Exception as exc:
        return {
            "status": "error",
            "provider": "stripe",
            "error": exc.__class__.__name__,
            "message": str(exc)[:300],
        }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
