"""Strict and PHI-safe multimodal adapter boundary tests."""
import json

import pytest
from PIL import Image

from engine.vision.base import VisionErrorType, parse_response
from engine.vision.gemini_engine import GeminiVisionEngine
from engine.vision.openai_engine import OpenAIVisionEngine


class _Reply:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_response_must_be_bare_json_with_exact_keys():
    valid = json.dumps({
        "value": "123", "visible_text": "123", "confidence": 0.9,
        "reason": "visible",
    })
    assert parse_response(valid, "model").ok

    prose = parse_response(f"result: {valid}", "model")
    missing = parse_response(json.dumps({"value": "123"}), "model")
    extra = parse_response(json.dumps({
        "value": "123", "visible_text": "123", "confidence": 0.9,
        "reason": "visible", "extra": "not allowed",
    }), "model")

    assert not prose.ok and not missing.ok and not extra.ok
    assert {prose.error_type, missing.error_type, extra.error_type} == {
        VisionErrorType.INVALID_RESPONSE
    }


def test_response_keeps_hash_not_raw_text():
    secret = json.dumps({
        "value": "sensitive", "visible_text": "sensitive", "confidence": 0.9,
        "reason": "visible",
    })
    response = parse_response(secret, "model")
    assert len(response.raw_sha256) == 64
    assert not hasattr(response, "raw")
    assert secret not in repr(response)


@pytest.mark.parametrize(
    ("module_name", "engine_class", "env_name", "payload"),
    [
        ("engine.vision.openai_engine", OpenAIVisionEngine, "OPENAI_API_KEY", {}),
        ("engine.vision.gemini_engine", GeminiVisionEngine, "GEMINI_API_KEY", []),
    ],
)
def test_malformed_provider_envelope_returns_typed_error(
        monkeypatch, module_name, engine_class, env_name, payload):
    monkeypatch.setenv(env_name, "synthetic-test-key")
    module = __import__(module_name, fromlist=["urllib"])
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: _Reply(payload))

    response = engine_class().read_field(
        Image.new("RGB", (20, 20), "white"), "patient_name")

    assert not response.ok
    assert response.error_type == VisionErrorType.INVALID_RESPONSE
    assert len(response.raw_sha256) == 64


def test_provider_timeout_returns_typed_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    import engine.vision.openai_engine as adapter
    monkeypatch.setattr(
        adapter.urllib.request, "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    response = OpenAIVisionEngine().read_field(
        Image.new("RGB", (20, 20), "white"), "patient_name")

    assert not response.ok
    assert response.error_type == VisionErrorType.TIMEOUT
