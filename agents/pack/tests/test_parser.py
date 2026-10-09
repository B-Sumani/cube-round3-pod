import pytest

from agents.pack.parser import (
    ModelObservation,
    ModelParsingError,
    ObservedItem,
    local_repair_json_string,
    parse_and_validate_observation,
)


def test_local_repair_code_fences_and_trailing_commas():
    malformed = """```json
    {
      "observed_items": [
        {
          "sku": "SKU-A",
          "count": 2,
          "count_confidence": 0.95,
          "identity_confidence": 0.98,
          "partially_occluded": false,
          "bbox": [10.0, 20.0, 100.0, 200.0],
        },
      ],
      "unrecognised_items": [],
      "image_quality": {"usable": true, "issues": [],},
      "occlusion_suspected": false,
      "notes": "test",
    }
    ```"""
    repaired = local_repair_json_string(malformed)
    assert not repaired.startswith("```")
    obs = parse_and_validate_observation(malformed, candidate_skus=["SKU-A"])
    assert len(obs.observed_items) == 1
    assert obs.observed_items[0].sku == "SKU-A"
    assert obs.observed_items[0].count == 2


def test_non_candidate_sku_is_demoted():
    raw = """{
      "observed_items": [
        {"sku": "SKU-A", "count": 1, "count_confidence": 0.9, "identity_confidence": 0.9, "partially_occluded": false, "bbox": [0,0,10,10]},
        {"sku": "SKU-ALIEN", "count": 1, "count_confidence": 0.8, "identity_confidence": 0.8, "partially_occluded": false, "bbox": [20,20,50,50]}
      ],
      "unrecognised_items": [],
      "image_quality": {"usable": true, "issues": []},
      "occlusion_suspected": false
    }"""
    obs = parse_and_validate_observation(raw, candidate_skus=["SKU-A"])
    assert len(obs.observed_items) == 1
    assert obs.observed_items[0].sku == "SKU-A"
    assert len(obs.unrecognised_items) == 1
    assert "SKU-ALIEN" in obs.unrecognised_items[0].description


def test_corrupt_payload_raises_parsing_error():
    with pytest.raises(ModelParsingError):
        parse_and_validate_observation("this is not json", candidate_skus=["SKU-A"])
