from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import requests

try:
    import jwt
except ImportError:  # pragma: no cover - reported as configuration error at runtime
    jwt = None

try:
    from .portal_governance import SQLiteGovernanceStore
except ImportError:  # pragma: no cover
    from portal_governance import SQLiteGovernanceStore


class StepUpError(ValueError):
    """Stable step-up authentication error exposed at the module interface."""


@dataclass(frozen=True)
class StepUpStart:
    authorization_url: str
    expires_in: int


class OIDCAdapter(Protocol):
    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        login_hint: str,
    ) -> str: ...

    def exchange_and_validate(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> dict[str, Any]: ...


class MicrosoftOIDCAdapter:
    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        timeout_seconds: int = 20,
    ):
        self.tenant_id = self._required(tenant_id, "entra_tenant_id")
        self.client_id = self._required(client_id, "entra_client_id")
        self.client_secret = self._required(client_secret, "entra_client_secret")
        self.redirect_uri = self._required(redirect_uri, "entra_redirect_uri")
        self.timeout_seconds = timeout_seconds
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        login_hint: str,
    ) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "response_mode": "query",
                "scope": "openid email profile",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "prompt": "login",
                "max_age": "0",
                "login_hint": login_hint,
            }
        )
        return f"{self.authority}/oauth2/v2.0/authorize?{query}"

    def exchange_and_validate(
        self,
        *,
        code: str,
        code_verifier: str,
        expected_nonce: str,
    ) -> dict[str, Any]:
        if jwt is None:
            raise StepUpError("pyjwt_not_installed")
        try:
            response = requests.post(
                f"{self.authority}/oauth2/v2.0/token",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": code_verifier,
                    "scope": "openid email profile",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            id_token = str(response.json()["id_token"])
            signing_key = jwt.PyJWKClient(
                f"{self.authority}/discovery/v2.0/keys"
            ).get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=f"{self.authority}/v2.0",
                options={"require": ["exp", "iat", "iss", "aud", "nonce"]},
            )
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise StepUpError("entra_token_exchange_failed") from exc
        except Exception as exc:
            raise StepUpError("entra_id_token_invalid") from exc
        if not hmac.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
            raise StepUpError("entra_nonce_mismatch")
        return claims

    @staticmethod
    def _required(value: str, field: str) -> str:
        clean = str(value or "").strip()
        if not clean:
            raise StepUpError(f"{field}_required")
        return clean


class LocalStepUpAdapter:
    """
    Identitaetsanbieter fuer die lokale Abnahme, wenn kein Entra erreichbar ist.

    Ersetzt ausschliesslich den Microsoft-Rueckkanal. Challenge, State, PKCE,
    Ablaufzeiten, Nonce- und E-Mail-Abgleich, Cookie und Auditeintrag der
    StepUpAuthority laufen unveraendert weiter. Lokal wird damit derselbe Ablauf
    geprueft wie in Produktion, nur die zweite Anmeldung bestaetigt der Nutzer
    auf einer lokalen Seite statt bei Microsoft.

    Darf niemals produktiv laufen. `main.py` aktiviert diesen Adapter nur, wenn
    keine einzige Entra-Variable gesetzt ist und das Flag ausdruecklich gesetzt
    wurde.
    """

    def __init__(self, *, confirm_url: str, signing_secret: str):
        if len(signing_secret) < 43:
            raise StepUpError("step_up_signing_secret_too_short")
        self.confirm_url = confirm_url
        self.secret = signing_secret.encode("utf-8")

    def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str, login_hint: str,
    ) -> str:
        query = urlencode({
            "state": state,
            "code": self._code(login_hint, nonce),
            "email": login_hint,
        })
        return f"{self.confirm_url}?{query}"

    def exchange_and_validate(
        self, *, code: str, code_verifier: str, expected_nonce: str,
    ) -> dict[str, Any]:
        email, nonce = self._decode(code)
        if not hmac.compare_digest(nonce, expected_nonce):
            raise StepUpError("local_step_up_nonce_mismatch")
        return {"preferred_username": email, "nonce": nonce}

    def _code(self, email: str, nonce: str) -> str:
        payload = json.dumps({"email": email, "nonce": nonce}, separators=(",", ":"))
        raw = payload.encode("utf-8")
        signature = hmac.new(self.secret, raw, hashlib.sha256).digest()
        return f"{self._b64url(raw)}.{self._b64url(signature)}"

    def _decode(self, code: str) -> tuple[str, str]:
        try:
            body, signature = code.split(".", 1)
            raw = self._b64url_decode(body)
            expected = hmac.new(self.secret, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(self._b64url_decode(signature), expected):
                raise StepUpError("local_step_up_code_signature_invalid")
            payload = json.loads(raw.decode("utf-8"))
            return str(payload["email"]).lower(), str(payload["nonce"])
        except StepUpError:
            raise
        except Exception as exc:
            raise StepUpError("local_step_up_code_invalid") from exc

    @staticmethod
    def _b64url(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class StepUpAuthority:
    COOKIE_NAME = "kahle_portal_step_up"

    def __init__(
        self,
        store: SQLiteGovernanceStore,
        oidc: OIDCAdapter,
        *,
        signing_secret: str,
        challenge_ttl_seconds: int = 300,
        proof_ttl_seconds: int = 600,
        clock=time.time,
    ):
        if len(signing_secret) < 43:
            raise StepUpError("step_up_signing_secret_too_short")
        self.store = store
        self.oidc = oidc
        self.secret = signing_secret.encode("utf-8")
        self.challenge_ttl_seconds = challenge_ttl_seconds
        self.proof_ttl_seconds = proof_ttl_seconds
        self.clock = clock
        self._initialize()

    def _initialize(self) -> None:
        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS step_up_challenges (
                    state_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES portal_users(user_id),
                    email TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    code_verifier TEXT NOT NULL,
                    return_to TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_step_up_expiry
                    ON step_up_challenges(expires_at);
                """
            )

    def begin(self, *, user_id: str, email: str, return_to: str = "/wissen/") -> StepUpStart:
        safe_return = self._safe_return_to(return_to)
        state = self._token(32)
        nonce = self._token(32)
        verifier = self._token(64)
        challenge = self._b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        now = int(self.clock())
        expires = now + self.challenge_ttl_seconds
        with self.store.connect() as db:
            db.execute("DELETE FROM step_up_challenges WHERE expires_at < ?", (now,))
            db.execute(
                """
                INSERT INTO step_up_challenges (
                    state_hash, user_id, email, nonce, code_verifier,
                    return_to, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._hash(state),
                    user_id,
                    email.lower(),
                    nonce,
                    verifier,
                    safe_return,
                    expires,
                    now,
                ),
            )
        return StepUpStart(
            authorization_url=self.oidc.authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                login_hint=email,
            ),
            expires_in=self.challenge_ttl_seconds,
        )

    def complete(
        self,
        *,
        current_user_id: str,
        state: str,
        code: str,
    ) -> tuple[str, str]:
        now = int(self.clock())
        state_hash = self._hash(state)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM step_up_challenges WHERE state_hash = ?", (state_hash,)
            ).fetchone()
            db.execute("DELETE FROM step_up_challenges WHERE state_hash = ?", (state_hash,))
        if not row or int(row["expires_at"]) < now:
            raise StepUpError("step_up_challenge_invalid_or_expired")
        if not hmac.compare_digest(str(row["user_id"]), current_user_id):
            raise StepUpError("step_up_user_mismatch")
        claims = self.oidc.exchange_and_validate(
            code=code,
            code_verifier=row["code_verifier"],
            expected_nonce=row["nonce"],
        )
        claim_email = str(
            claims.get("preferred_username") or claims.get("email") or ""
        ).lower()
        if not claim_email or not hmac.compare_digest(claim_email, str(row["email"])):
            raise StepUpError("step_up_email_mismatch")
        proof = self._issue_proof(current_user_id, claim_email, now)
        return proof, str(row["return_to"])

    def verify(self, proof: str, *, user_id: str) -> dict[str, Any]:
        try:
            payload_raw, signature_raw = proof.split(".", 1)
            expected = hmac.new(self.secret, payload_raw.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(self._b64url(expected), signature_raw):
                raise StepUpError("step_up_proof_invalid")
            payload = json.loads(self._b64url_decode(payload_raw))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise StepUpError("step_up_proof_invalid") from exc
        now = int(self.clock())
        if payload.get("purpose") != "portal_sensitive_action":
            raise StepUpError("step_up_proof_invalid")
        if not hmac.compare_digest(str(payload.get("sub") or ""), user_id):
            raise StepUpError("step_up_user_mismatch")
        if int(payload.get("exp") or 0) < now or int(payload.get("iat") or 0) > now:
            raise StepUpError("step_up_proof_expired")
        return payload

    def _issue_proof(self, user_id: str, email: str, now: int) -> str:
        payload = self._b64url(
            json.dumps(
                {
                    "sub": user_id,
                    "email": email,
                    "purpose": "portal_sensitive_action",
                    "iat": now,
                    "exp": now + self.proof_ttl_seconds,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signature = self._b64url(
            hmac.new(self.secret, payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{payload}.{signature}"

    @staticmethod
    def _safe_return_to(value: str) -> str:
        clean = str(value or "").strip()
        if not clean.startswith("/") or clean.startswith("//") or "\\" in clean:
            return "/wissen/"
        return clean

    @staticmethod
    def _token(bytes_count: int) -> str:
        return secrets.token_urlsafe(bytes_count)

    def _hash(self, value: str) -> str:
        return hmac.new(self.secret, str(value).encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _b64url(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
