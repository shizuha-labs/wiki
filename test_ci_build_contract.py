from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_container_build_tolerates_bounded_cold_cache_fills():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "PIP_DEFAULT_TIMEOUT=180" in dockerfile
    assert "PIP_RETRIES=20" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile
