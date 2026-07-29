from pathlib import Path


STACK = Path(__file__).resolve().parents[1]


def test_edge_compose_has_no_application_dependency_or_network():
    src = (STACK / "docker-compose.edge.yml").read_text(encoding="utf-8")

    assert "caddy:2.11.3-alpine" in src
    assert '"0.0.0.0:80:80"' in src
    assert '"0.0.0.0:443:443"' in src
    assert "open-webui" not in src
    assert "owui-file-proxy" not in src
    assert "reverse_proxy" not in src


def test_maintenance_caddyfile_never_proxies_to_the_application():
    src = (STACK / "caddy" / "Caddyfile.maintenance").read_text(encoding="utf-8")

    assert "{$PUBLIC_HOSTNAME}" in src
    assert "respond \"ok\" 200" in src
    assert "HTML 503" in src
    assert "reverse_proxy" not in src
    assert "Content-Security-Policy" in src
    assert "Cache-Control \"no-store\"" in src