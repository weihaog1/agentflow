from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_compose_published_ports_are_loopback_only() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.yml").read_text()

    for published_port in (
        '"127.0.0.1:8000:8000"',
        '"127.0.0.1:3000:8080"',
        '"127.0.0.1:9000:9000"',
        '"127.0.0.1:9001:9001"',
    ):
        assert compose.count(published_port) == 1
    for unsafe_port in ('"8000:8000"', '"3000:8080"', '"9000:9000"', '"9001:9001"'):
        assert unsafe_port not in compose


def test_frontend_proxy_matches_backend_upload_limit() -> None:
    config = (REPOSITORY_ROOT / "infra" / "docker" / "nginx.conf").read_text()

    assert "client_max_body_size 25m;" in config
    assert "location = /metrics" in config
    assert "proxy_pass http://api:8000/metrics;" in config
