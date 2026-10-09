import pytest

from agents.pack.model_adapter import (
    GeminiVisionAdapter,
    MockVisionAdapter,
    ModelProviderError,
)
from agents.pack.parser import ModelObservation, ObservedItem


def test_missing_api_key_raises_provider_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    adapter = GeminiVisionAdapter(api_key=None)
    with pytest.raises(ModelProviderError) as exc_info:
        adapter.analyze_box(b"fake_jpeg", candidate_skus=["SKU-A"])
    assert "GEMINI_API_KEY is not configured" in str(exc_info.value)


def test_mock_adapter_is_injectable_for_tests():
    obs = ModelObservation(
        observed_items=[ObservedItem(sku="SKU-A", count=1, count_confidence=0.9, identity_confidence=0.9)]
    )
    mock = MockVisionAdapter(mock_observation=obs)
    res_obs, latency, info = mock.analyze_box(b"fake_image", candidate_skus=["SKU-A"])
    assert mock.call_count == 1
    assert len(res_obs.observed_items) == 1
    assert res_obs.observed_items[0].sku == "SKU-A"
    assert info["name"] == "mock-adapter"
