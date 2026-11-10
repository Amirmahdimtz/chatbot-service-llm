"""Static validation supplements (not replaces) docker compose config and live tests."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_restricted_ports_and_named_data_volumes():
    document = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = document["services"]
    assert set(services) == {"app", "postgres", "qdrant"}
    assert all(port.startswith("127.0.0.1:") for service in services.values() for port in service["ports"])
    assert services["app"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["app"]["depends_on"]["qdrant"]["condition"] == "service_healthy"
    assert set(document["volumes"]) == {"postgres_data", "qdrant_data"}
    assert any("postgres_data" in str(volume) for volume in services["postgres"]["volumes"])
    assert any("qdrant_data" in str(volume) for volume in services["qdrant"]["volumes"])
    assert "latest" not in services["postgres"]["image"]
    assert "latest" not in services["qdrant"]["image"]
    assert not any(key.startswith("POSTGRES_PASSWORD") for key in document.get("environment", {}))


def test_secrets_not_in_defaults_and_environment_template_is_committable():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD=\n" in example
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!.env.example" in ignored
    assert "storage/" in ignored
    production = yaml.safe_load((ROOT / "src/host/res/appsettings.yaml").read_text(encoding="utf-8"))
    assert production["database"]["url"] == ""
    assert production["llm"]["base_url"] == ""
    assert production["vector"]["url"] == ""


def test_shell_entrypoint_is_normalized_for_windows_checkout():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "RUN sed -i 's/\\r$//' /app/src/host/entrypoint.sh" in dockerfile
    entrypoint = (ROOT / "src/host/entrypoint.sh").read_bytes()
    assert b"\r" not in entrypoint


def test_pip_index_build_argument_and_local_mirror_template():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["services"]["app"]["build"]["args"]["PIP_INDEX_URL"] == "${CHATBOT_PIP_INDEX_URL:-https://pypi.org/simple/}"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG PIP_INDEX_URL=https://pypi.org/simple/" in dockerfile
    assert '--index-url "$PIP_INDEX_URL"' in dockerfile
    assert "--trusted-host" not in dockerfile
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "CHATBOT_PIP_INDEX_URL=https://mirror-pypi.runflare.com/simple/" in template
