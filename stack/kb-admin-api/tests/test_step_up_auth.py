from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, APP / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


governance_module = load("portal_governance")
step_up_module = load("step_up_auth")


class FakeOIDC:
    def __init__(self):
        self.nonce = ""
        self.verifier = ""

    def authorization_url(self, *, state, nonce, code_challenge, login_hint):
        self.nonce = nonce
        assert code_challenge
        return f"https://login.example/authorize?state={state}&login_hint={login_hint}"

    def exchange_and_validate(self, *, code, code_verifier, expected_nonce):
        assert code == "valid-code"
        assert code_verifier
        assert expected_nonce == self.nonce
        self.verifier = code_verifier
        return {
            "nonce": expected_nonce,
            "preferred_username": "portal@kahle.de",
            "sub": "entra-subject",
        }


def setup(root: Path, clock_value: list[float]):
    store = governance_module.SQLiteGovernanceStore(root / "portal.sqlite3")
    governance = governance_module.PortalGovernance(store)
    governance.sync_identity(
        user_id="portal",
        email="portal@kahle.de",
        display_name="Portal",
        bootstrap_portal_admin=True,
    )
    oidc = FakeOIDC()
    authority = step_up_module.StepUpAuthority(
        store,
        oidc,
        signing_secret="s" * 64,
        challenge_ttl_seconds=300,
        proof_ttl_seconds=600,
        clock=lambda: clock_value[0],
    )
    return authority, oidc


def test_step_up_is_bound_to_user_email_nonce_and_short_lived_proof():
    with tempfile.TemporaryDirectory() as directory:
        clock = [1_786_000_000.0]
        authority, oidc = setup(Path(directory), clock)
        started = authority.begin(
            user_id="portal", email="portal@kahle.de", return_to="/wissen/admin"
        )
        query = parse_qs(urlparse(started.authorization_url).query)
        proof, return_to = authority.complete(
            current_user_id="portal", state=query["state"][0], code="valid-code"
        )
        assert oidc.verifier
        assert return_to == "/wissen/admin"
        verified = authority.verify(proof, user_id="portal")
        assert verified["email"] == "portal@kahle.de"

        clock[0] += 601
        try:
            authority.verify(proof, user_id="portal")
            raise AssertionError("step-up proof must expire")
        except step_up_module.StepUpError as exc:
            assert str(exc) == "step_up_proof_expired"


def test_challenge_is_single_use_and_bound_to_current_openwebui_user():
    with tempfile.TemporaryDirectory() as directory:
        clock = [1_786_000_000.0]
        authority, _ = setup(Path(directory), clock)
        started = authority.begin(user_id="portal", email="portal@kahle.de")
        state = parse_qs(urlparse(started.authorization_url).query)["state"][0]
        try:
            authority.complete(
                current_user_id="someone-else", state=state, code="valid-code"
            )
            raise AssertionError("challenge must be bound to current OpenWebUI user")
        except step_up_module.StepUpError as exc:
            assert str(exc) == "step_up_user_mismatch"
        try:
            authority.complete(current_user_id="portal", state=state, code="valid-code")
            raise AssertionError("challenge must be consumed after one attempt")
        except step_up_module.StepUpError as exc:
            assert str(exc) == "step_up_challenge_invalid_or_expired"


if __name__ == "__main__":
    test_step_up_is_bound_to_user_email_nonce_and_short_lived_proof()
    test_challenge_is_single_use_and_bound_to_current_openwebui_user()
    print("step-up auth tests passed")


def test_local_adapter_round_trips_email_and_nonce():
    adapter = step_up_module.LocalStepUpAdapter(
        confirm_url="/wissen/api/portal/auth/step-up/local-confirm",
        signing_secret="x" * 43,
    )
    url = adapter.authorization_url(
        state="s", nonce="n-123", code_challenge="c", login_hint="portal@kahle.de",
    )
    assert url.startswith("/wissen/api/portal/auth/step-up/local-confirm?")
    code = parse_qs(urlparse(url).query)["code"][0]

    claims = adapter.exchange_and_validate(
        code=code, code_verifier="ignored", expected_nonce="n-123",
    )
    assert claims["preferred_username"] == "portal@kahle.de"


def test_local_adapter_rejects_a_replayed_or_forged_code():
    adapter = step_up_module.LocalStepUpAdapter(
        confirm_url="/confirm", signing_secret="x" * 43,
    )
    url = adapter.authorization_url(
        state="s", nonce="n-123", code_challenge="c", login_hint="portal@kahle.de",
    )
    code = parse_qs(urlparse(url).query)["code"][0]

    # Nonce einer anderen Challenge darf nicht durchgehen.
    try:
        adapter.exchange_and_validate(code=code, code_verifier="", expected_nonce="andere")
    except step_up_module.StepUpError as error:
        assert str(error) == "local_step_up_nonce_mismatch"
    else:
        raise AssertionError("foreign nonce was accepted")

    # Mit fremdem Schluessel signierter Code darf nicht durchgehen.
    forged = step_up_module.LocalStepUpAdapter(
        confirm_url="/confirm", signing_secret="y" * 43,
    ).authorization_url(
        state="s", nonce="n-123", code_challenge="c", login_hint="angreifer@kahle.de",
    )
    forged_code = parse_qs(urlparse(forged).query)["code"][0]
    try:
        adapter.exchange_and_validate(
            code=forged_code, code_verifier="", expected_nonce="n-123",
        )
    except step_up_module.StepUpError as error:
        assert str(error) == "local_step_up_code_signature_invalid"
    else:
        raise AssertionError("forged code was accepted")
