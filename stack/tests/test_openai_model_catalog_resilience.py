import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTER_PATH = REPO_ROOT / "stack/open-webui-overrides/open_webui/routers/openai.py"
COMPOSE_PATH = REPO_ROOT / "stack/docker-compose.yml"


def _load_recovery_helpers():
    source = ROUTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "_model_list_request_failed",
        "_configured_model_fallback",
        "_recover_model_catalog",
    }
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {
        "_MODEL_FALLBACK_IDS": (
            "mistralai/Mistral-Small-24B-Instruct",
            "openai/gpt-oss-120b",
            "Qwen/Qwen3.5-397B-A17B",
        )
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(ROUTER_PATH), "exec"),
        namespace,
    )
    return namespace["_recover_model_catalog"]


def test_successful_model_catalog_is_used():
    recover = _load_recovery_helpers()
    current = {"model-a": {"id": "model-a"}}
    previous = {"model-old": {"id": "model-old"}}

    models, source = recover(current, previous, [{"data": [{"id": "model-a"}]}])

    assert models == current
    assert source == ""


def test_successful_empty_catalog_is_not_replaced():
    recover = _load_recovery_helpers()
    previous = {"model-old": {"id": "model-old"}}

    models, source = recover({}, previous, [{"data": []}])

    assert models == {}
    assert source == ""


def test_failed_catalog_uses_last_known_good_models():
    recover = _load_recovery_helpers()
    previous = {"model-old": {"id": "model-old"}}

    models, source = recover({}, previous, [None])

    assert models == previous
    assert source == "last-known-good"


def test_failed_first_catalog_uses_configured_fallback_models():
    recover = _load_recovery_helpers()

    models, source = recover({}, {}, [{"error": "upstream unavailable"}])

    assert source == "configured-fallback"
    assert set(models) == {
        "mistralai/Mistral-Small-24B-Instruct",
        "openai/gpt-oss-120b",
        "Qwen/Qwen3.5-397B-A17B",
    }
    assert all(model["urlIdx"] == 0 for model in models.values())


def test_router_and_compose_enable_resilient_model_catalog():
    router = ROUTER_PATH.read_text(encoding="utf-8")
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "range(_MODEL_LIST_RETRIES)" in router
    assert "await asyncio.sleep(_MODEL_LIST_RETRY_DELAY_SECONDS" in router
    assert "previous_models = dict(" in router
    assert (
        "open_webui/routers/openai.py:/app/backend/open_webui/routers/openai.py:ro"
        in compose
    )
    assert 'IONOS_MODEL_LIST_RETRIES: "3"' in compose
    assert "IONOS_MODEL_FALLBACK_IDS:" in compose