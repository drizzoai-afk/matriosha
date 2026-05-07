"""FastAPI app factory for local-only agent inspection and memory access."""

from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any, Literal

import numpy as np
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from matriosha.cli.commands.memory.common import (
    _SEMANTIC_PREVIEW_CHARS,
    _SEMANTIC_SEARCH_TEXT_LIMIT,
    _decode_with_corruption_handling,
    _semantic_from_plaintext,
    _validate_tags,
)
from matriosha.core.binary_protocol import encode_envelope
from matriosha.core.local_tokens import (
    LocalTokenError,
    revoke_local_agent_token,
    verify_local_agent_token,
)
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import AuthError, Vault, VaultError, VaultIntegrityError
from matriosha.core.vectors import LocalVectorIndex, get_default_embedder


class MemoryCreateRequest(BaseModel):
    """Request body for creating a local encrypted memory."""

    text: str
    tags: list[str] = Field(default_factory=list)


class MemoryCreateResponse(BaseModel):
    """Response body for created memory."""

    status: Literal["ok"]
    memory_id: str
    bytes: int
    tags: list[str]
    merkle_root: str


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing bearer token")

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="invalid authorization header")

    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="empty bearer token")
    return token


def _verify_agent(
    *,
    profile_name: str,
    authorization: str | None,
    required_scope: str = "read",
) -> dict[str, Any]:
    token = _extract_bearer_token(authorization)
    try:
        verified = verify_local_agent_token(
            profile_name=profile_name,
            token_plaintext=token,
            required_scope=required_scope,
        )
    except LocalTokenError as exc:
        raise HTTPException(
            status_code=401 if exc.code.endswith("401") else 403, detail=exc.message
        ) from exc
    return verified


def _unlock_vault(
    profile_name: str,
    passphrase: str | None,
    *,
    agent_id: str | None = None,
) -> Vault:
    if not passphrase:
        raise HTTPException(status_code=401, detail="missing vault passphrase")

    try:
        return Vault.unlock(profile_name, passphrase)
    except AuthError as exc:
        if agent_id:
            revoke_local_agent_token(profile_name, agent_id)
        raise HTTPException(status_code=401, detail="invalid vault passphrase") from exc
    except (VaultError, VaultIntegrityError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=500, detail=f"vault unlock failed: {type(exc).__name__}"
        ) from exc


def _memory_preview(
    *,
    profile_name: str,
    memory_id: str,
    passphrase: str,
    agent_id: str | None = None,
    text_limit: int = _SEMANTIC_PREVIEW_CHARS,
) -> dict[str, Any]:
    vault = _unlock_vault(profile_name, passphrase, agent_id=agent_id)
    store = LocalStore(profile_name)

    try:
        env, b64_payload = store.get(memory_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="memory not found") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid memory id: {memory_id}") from exc

    plaintext, integrity_warning, restored_from_backup = _decode_with_corruption_handling(
        env=env,
        b64_payload=b64_payload,
        key=vault.data_key,
        profile_mode="local",
        memory_id=env.memory_id,
        store=store,
    )

    if plaintext is None:
        semantic: dict[str, Any] = {
            "kind": "corrupted",
            "filename": getattr(env, "filename", None),
            "mime_type": getattr(env, "mime_type", None),
            "preview": "Unavailable: encrypted memory failed integrity checks",
            "metadata": {
                "input_bytes": int(getattr(env, "plaintext_bytes", None) or 0),
                "blocks": len(getattr(env, "merkle_leaves", []) or []),
            },
            "warnings": [],
        }
        plaintext_b64 = None
        bytes_count = 0
    else:
        semantic = _semantic_from_plaintext(
            plaintext=plaintext,
            envelope_tags=env.tags,
            memory_id=env.memory_id,
            text_limit=text_limit,
            filename=getattr(env, "filename", None),
            mime_type=getattr(env, "mime_type", None),
            content_kind=getattr(env, "content_kind", None),
        )
        plaintext_b64 = base64.b64encode(plaintext).decode("ascii")
        bytes_count = len(plaintext)

    safe_integrity_warning = None
    if integrity_warning:
        safe_integrity_warning = "Encrypted memory failed integrity checks"
        warnings = list(semantic.get("warnings") or [])
        warnings.append(safe_integrity_warning)
        semantic["warnings"] = warnings

    return {
        "memory_id": env.memory_id,
        "bytes": bytes_count,
        "tags": env.tags,
        "created_at": env.created_at,
        "plaintext_b64": plaintext_b64,
        "preview": str(semantic.get("preview") or "")[:text_limit],
        "semantic": semantic,
        "integrity_warning": safe_integrity_warning,
        "restored_from_backup": restored_from_backup,
        "envelope": asdict(env),
    }


def create_local_app(*, profile_name: str) -> FastAPI:
    """Create a local-only FastAPI app for loopback agent access."""

    app = FastAPI(title="Matriosha Local Agent API", version="1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "local"}

    @app.get("/agent")
    def agent(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        verified = _verify_agent(profile_name=profile_name, authorization=authorization)
        return {
            "status": "ok",
            "mode": "local",
            "agent": verified,
        }

    @app.post("/token/verify")
    def token_verify(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        verified = _verify_agent(profile_name=profile_name, authorization=authorization)
        return {
            "status": "ok",
            "mode": "local",
            "token": verified,
        }

    @app.get("/memories")
    def list_memories(
        authorization: str | None = Header(default=None),
        tag: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        _verify_agent(profile_name=profile_name, authorization=authorization, required_scope="read")
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")

        store = LocalStore(profile_name)
        try:
            envelopes = store.list(tag=tag, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "status": "ok",
            "mode": "local",
            "memories": [
                {
                    "memory_id": env.memory_id,
                    "tags": env.tags,
                    "created_at": env.created_at,
                    "bytes": getattr(env, "plaintext_bytes", None),
                    "content_kind": getattr(env, "content_kind", None),
                    "filename": getattr(env, "filename", None),
                    "mime_type": getattr(env, "mime_type", None),
                }
                for env in envelopes
            ],
        }

    @app.post("/memories", response_model=MemoryCreateResponse)
    def create_memory(
        request: MemoryCreateRequest,
        authorization: str | None = Header(default=None),
        x_matriosha_vault_passphrase: str | None = Header(default=None),
    ) -> MemoryCreateResponse:
        verified = _verify_agent(
            profile_name=profile_name, authorization=authorization, required_scope="write"
        )
        vault = _unlock_vault(
            profile_name,
            x_matriosha_vault_passphrase,
            agent_id=str(verified.get("id") or ""),
        )

        try:
            tags = _validate_tags(request.tags)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload = request.text.encode("utf-8")
        env, b64_payload = encode_envelope(
            payload,
            vault.data_key,
            mode="local",
            tags=tags,
            source="agent",
            filename=None,
            mime_type="text/plain",
            content_kind="text",
        )

        store = LocalStore(profile_name)
        embedding = get_default_embedder().embed(request.text[:4096])
        store.put(env, b64_payload, embedding=np.asarray(embedding, dtype=np.float32))

        return MemoryCreateResponse(
            status="ok",
            memory_id=env.memory_id,
            bytes=len(payload),
            tags=tags,
            merkle_root=env.merkle_root,
        )

    @app.get("/memories/search")
    def search_memories(
        q: str,
        authorization: str | None = Header(default=None),
        x_matriosha_vault_passphrase: str | None = Header(default=None),
        k: int = 10,
        threshold: float = 0.0,
        tag: str | None = None,
    ) -> dict[str, Any]:
        verified = _verify_agent(
            profile_name=profile_name, authorization=authorization, required_scope="read"
        )
        if k < 1 or k > 100:
            raise HTTPException(status_code=400, detail="k must be between 1 and 100")
        if threshold < -1.0 or threshold > 1.0:
            raise HTTPException(status_code=400, detail="threshold must be between -1.0 and 1.0")

        query_vec = get_default_embedder().embed(q)
        index = LocalVectorIndex(profile_name)
        candidates = index.search(query_vec, k=k)

        results = []
        for memory_id, score in candidates:
            if score < threshold:
                continue
            item = _memory_preview(
                profile_name=profile_name,
                memory_id=memory_id,
                passphrase=x_matriosha_vault_passphrase or "",
                agent_id=str(verified.get("id") or ""),
                text_limit=_SEMANTIC_SEARCH_TEXT_LIMIT,
            )
            if tag is not None and tag not in item["tags"]:
                continue
            results.append(
                {
                    "memory_id": memory_id,
                    "score": score,
                    "tags": item["tags"],
                    "created_at": item["created_at"],
                    "preview": item["preview"],
                    "semantic": item["semantic"],
                    "integrity_warning": item["integrity_warning"],
                    "restored_from_backup": item["restored_from_backup"],
                }
            )

        return {
            "status": "ok",
            "mode": "local",
            "query": q,
            "k": k,
            "threshold": threshold,
            "tag": tag,
            "results": results,
        }

    @app.get("/memories/{memory_id}")
    def get_memory(
        memory_id: str,
        authorization: str | None = Header(default=None),
        x_matriosha_vault_passphrase: str | None = Header(default=None),
    ) -> dict[str, Any]:
        verified = _verify_agent(
            profile_name=profile_name, authorization=authorization, required_scope="read"
        )
        return {
            "status": "ok",
            "mode": "local",
            "memory": _memory_preview(
                profile_name=profile_name,
                memory_id=memory_id,
                passphrase=x_matriosha_vault_passphrase or "",
                agent_id=str(verified.get("id") or ""),
            ),
        }

    @app.delete("/memories/{memory_id}")
    def delete_memory(
        memory_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _verify_agent(
            profile_name=profile_name, authorization=authorization, required_scope="write"
        )
        store = LocalStore(profile_name)
        try:
            deleted = store.delete(memory_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "mode": "local", "memory_id": memory_id, "deleted": deleted}

    return app
