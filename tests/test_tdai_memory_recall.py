import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from tdai_memory.recall import _rrf_fusion


def test_rrf_fusion_returns_ranked_results_without_name_error():
    keyword_results = [
        {"id": "mem-1", "content": "keyword hit", "score": 0.9},
        {"id": "mem-2", "content": "keyword only", "score": 0.8},
    ]
    vector_results = [
        {"id": "mem-1", "content": "vector hit", "score": 0.95},
        {"id": "mem-3", "content": "vector only", "score": 0.7},
    ]

    fused = _rrf_fusion(keyword_results, vector_results)

    assert [item["id"] for item in fused] == ["mem-1", "mem-2", "mem-3"]
    assert fused[0]["_source"] == "keyword"
    assert fused[0]["_rrf_score"] > fused[1]["_rrf_score"]
