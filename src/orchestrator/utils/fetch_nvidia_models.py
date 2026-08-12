import os


def fetch_nvidia_models(
    api_key: str | None = None,
    only_chat: bool = True,
    only_active: bool = True,
    only_tool_supporting: bool = True,
) -> list[dict[str, str]]:
    """
    Fetches available models from NVIDIA AI Endpoints for LangChain.
    Filters out deprecated models and models that do not support tool-calling if requested.
    Requires NVIDIA_API_KEY environment variable or explicitly passed api_key.
    """
    key = api_key or os.getenv("NVIDIA_API_KEY")
    if not key:
        return []

    try:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        # Query NVIDIA API endpoints catalog
        all_models = ChatNVIDIA.get_available_models(api_key=key)

        model_list = []
        for m in all_models:
            model_id = getattr(m, "id", str(m))
            model_type = getattr(m, "model_type", "chat")
            is_deprecated = getattr(m, "deprecated", False)
            supports_tools = getattr(m, "supports_tools", False)

            KNOWN_EOL_MODELS = {
                "stepfun-ai/step-3.5-flash",
                "bytedance/seed-oss-36b-instruct",
                "qwen/qwen3-next-80b-a3b-instruct",
                "qwen/qwen3-next-80b-a3b-thinking",
                "microsoft/phi-4-mini-instruct",
                "z-ai/glm-5.1",
                "moonshotai/kimi-k2-instruct",
                "moonshotai/kimi-k2-instruct-0905",
                "moonshotai/kimi-k2-thinking",
                "deepseek-ai/deepseek-v3.1-terminus",
                "deepseek-ai/deepseek-v3.2",
            }
            if model_id in KNOWN_EOL_MODELS:
                continue

            if only_chat and model_type != "chat":
                continue
            if only_active and is_deprecated:
                continue
            if only_tool_supporting and not supports_tools:
                continue

            model_list.append(
                {
                    "id": model_id,
                    "type": model_type,
                    "deprecated": is_deprecated,
                    "supports_tools": supports_tools,
                }
            )

        return model_list

    except Exception as e:  # noqa: BLE001
        print(f"Error fetching NVIDIA models: {e}")
        return []


if __name__ == "__main__":
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")

    print("[NVIDIA Models] Fetching available NVIDIA AI models for LangChain...\n")
    models = fetch_nvidia_models()

    if models:
        print(f"[SUCCESS] {len(models)} NVIDIA models found:\n")
        print(f"{'Model ID':<55} | {'Type':<15}")
        print("-" * 75)
        for m in models:
            print(f"{m['id']:<55} | {m['type']:<15}")
    else:
        print("[WARNING] No models found or NVIDIA_API_KEY is not set.")
        print(
            "Please set your API key in PowerShell e.g. via: $env:NVIDIA_API_KEY='nvapi-...'"
        )
