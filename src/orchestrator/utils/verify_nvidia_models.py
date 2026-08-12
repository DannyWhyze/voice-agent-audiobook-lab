import concurrent.futures
from pathlib import Path

from langchain_nvidia_ai_endpoints import ChatNVIDIA

from .fetch_nvidia_models import fetch_nvidia_models


def probe_single_model(model_id: str) -> tuple[str, bool, str | None]:
    """Probes a single NVIDIA model to check if it responds cleanly without 410 EOL or 404."""
    try:
        llm = ChatNVIDIA(model=model_id, max_completion_tokens=1)
        llm.invoke("Hi")
        return (model_id, True, None)
    except Exception as e:  # noqa: BLE001
        return (model_id, False, str(e))


def fetch_verified_nvidia_models(
    api_key: str | None = None, max_workers: int = 10
) -> list[dict[str, str]]:
    """
    Fetches NVIDIA models and runs a parallel live health check probe.
    Returns ONLY models that are active, support tools, AND respond 200 OK.
    """
    raw_models = fetch_nvidia_models(api_key=api_key)
    if not raw_models:
        return []

    model_ids = [m["id"] for m in raw_models]
    verified_models = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(probe_single_model, model_ids))

    for m_id, is_ok, err in results:
        if is_ok:
            verified_models.append({"id": m_id, "type": "chat"})
        else:
            print(f"[MODEL FILTERED] {m_id} failed live probe: {str(err)[:100]}")

    return verified_models


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")

    print("[NVIDIA Prober] Testing live responsiveness of candidate models...")
    verified = fetch_verified_nvidia_models()
    print(f"\n[PROBE COMPLETE] {len(verified)} verified working models found:")
    for v in verified:
        print(f"  [OK] {v['id']}")
