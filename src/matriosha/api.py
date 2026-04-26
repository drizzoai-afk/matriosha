from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
import base64
import os

app = FastAPI()


class OtpStartRequest(BaseModel):
    email: str


class OtpVerifyRequest(BaseModel):
    email: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VaultCustodyRequest(BaseModel):
    action: str
    kdf_salt_b64: str | None = None
    wrapped_key_b64: str | None = None
    algo: str | None = None


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=400, detail="valid email is required")
    return normalized


def _bytea_to_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        if value.startswith("\\x"):
            return bytes.fromhex(value[2:])
        return value.encode("utf-8")
    raise HTTPException(status_code=500, detail="stored key material has unsupported shape")


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_DIAGNOSTICS_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="admin diagnostics token not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=404, detail="not found")


def _supabase_anon_client():
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise HTTPException(status_code=503, detail="supabase auth is not configured")
    return create_client(url, key)


def _supabase_service_client():
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise HTTPException(status_code=503, detail="supabase service role is not configured")
    return create_client(url, key)


def _ensure_public_user(user_id: str) -> None:
    db = _supabase_service_client()
    db.table("users").upsert({"id": user_id}, on_conflict="id").execute()


@app.post("/managed/auth/otp/start")
def managed_auth_otp_start(req: OtpStartRequest):
    client = _supabase_anon_client()
    try:
        result = client.auth.sign_in_with_otp(
            {
                "email": _normalize_email(req.email),
                "options": {
                    "should_create_user": True,
                },
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not send login code: {exc.__class__.__name__}") from exc

    return {
        "status": "ok",
        "message": "login code sent",
        "message_id": getattr(result, "message_id", None),
    }


@app.post("/managed/auth/otp/verify")
def managed_auth_otp_verify(req: OtpVerifyRequest):
    code = req.code.strip().replace(" ", "")
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    client = _supabase_anon_client()
    try:
        result = client.auth.verify_otp(
            {
                "email": _normalize_email(req.email),
                "token": code,
                "type": "email",
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid or expired login code: {exc.__class__.__name__}") from exc

    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    access_token = getattr(session, "access_token", None) if session else None
    refresh_token = getattr(session, "refresh_token", None) if session else None
    expires_in = getattr(session, "expires_in", None) if session else None
    token_type = getattr(session, "token_type", None) if session else "bearer"

    if not access_token:
        raise HTTPException(status_code=401, detail="login verification did not return a session")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "token_type": token_type or "bearer",
        "scope": "openid profile email offline_access",
        "user": {
            "id": getattr(user, "id", None) if user else None,
            "email": getattr(user, "email", None) if user else _normalize_email(req.email),
        },
    }


@app.post("/managed/auth/refresh")
def managed_auth_refresh(req: RefreshRequest):
    refresh_token = req.refresh_token.strip()
    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token is required")

    client = _supabase_anon_client()
    try:
        result = client.auth.refresh_session(refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid or expired refresh token: {exc.__class__.__name__}") from exc

    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    access_token = getattr(session, "access_token", None) if session else None
    rotated_refresh = getattr(session, "refresh_token", None) if session else None
    expires_in = getattr(session, "expires_in", None) if session else None
    token_type = getattr(session, "token_type", None) if session else "bearer"

    if not access_token:
        raise HTTPException(status_code=401, detail="token refresh did not return an access token")

    return {
        "access_token": access_token,
        "refresh_token": rotated_refresh or refresh_token,
        "expires_in": expires_in,
        "token_type": token_type or "bearer",
        "scope": "openid profile email offline_access",
        "user": {
            "id": getattr(user, "id", None) if user else None,
            "email": getattr(user, "email", None) if user else None,
        },
    }


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="invalid authorization header")
    return token.strip()


@app.get("/managed/whoami")
def managed_whoami(authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    client = _supabase_anon_client()
    try:
        result = client.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid session: {exc.__class__.__name__}") from exc

    user = getattr(result, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="invalid session")

    user_id = getattr(user, "id", None)
    if user_id:
        _ensure_public_user(str(user_id))

    return {
        "user_id": user_id,
        "id": user_id,
        "email": getattr(user, "email", None),
        "aud": getattr(user, "aud", None),
        "role": getattr(user, "role", None),
    }


@app.post("/functions/v1/vault-custody")
def vault_custody(req: VaultCustodyRequest, authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    auth_client = _supabase_anon_client()
    try:
        user_result = auth_client.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid session: {exc.__class__.__name__}") from exc

    user = getattr(user_result, "user", None)
    user_id = getattr(user, "id", None) if user else None
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid session")

    user_id = str(user_id)
    _ensure_public_user(user_id)
    db = _supabase_service_client()

    if req.action == "fetch":
        result = (
            db.table("vault_keys")
            .select("kdf_salt,wrapped_key,algo")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            raise HTTPException(status_code=404, detail="managed vault key not found")

        row = rows[0]
        return {
            "kdf_salt_b64": base64.b64encode(_bytea_to_bytes(row["kdf_salt"])).decode("ascii"),
            "wrapped_key_b64": base64.b64encode(_bytea_to_bytes(row["wrapped_key"])).decode("ascii"),
            "algo": row.get("algo") or "aes-gcm",
        }

    if req.action == "upsert":
        if not req.kdf_salt_b64 or not req.wrapped_key_b64:
            raise HTTPException(status_code=400, detail="kdf_salt_b64 and wrapped_key_b64 are required")
        try:
            kdf_salt = base64.b64decode(req.kdf_salt_b64, validate=True)
            wrapped_key = base64.b64decode(req.wrapped_key_b64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid base64 key material") from exc

        row = {
            "user_id": user_id,
            "kdf_salt": "\\x" + kdf_salt.hex(),
            "wrapped_key": "\\x" + wrapped_key.hex(),
            "algo": req.algo or "aes-gcm",
        }
        db.table("vault_keys").upsert(row, on_conflict="user_id").execute()
        return {"status": "ok"}

    raise HTTPException(status_code=400, detail="unsupported vault custody action")


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
