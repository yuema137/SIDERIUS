import os
from pathlib import Path

from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")


def test_openai():
    print("\n" + "=" * 10 + " Testing OpenAI " + "=" * 10)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not found in .env")
        return False

    try:
        bridge = LLMBridge(provider="openai")

        # 1. List available models
        print("Available OpenAI Models (Top 5):")
        models = bridge.list_models()
        for m in models[:5]:
            print(f"  - {m}")
        print(f"  ... (Total {len(models)} models found)")

        # 2. Test completion
        result = bridge.generate_text(
            system_prompt="You are a helpful assistant.",
            user_prompt="say ok",
        )
        print(f"OpenAI Response: {result}")
        return True
    except Exception as e:
        print(f"OpenAI failed: {e}")
        return False


def test_gemini():
    print("\n" + "=" * 10 + " Testing Gemini " + "=" * 10)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found in .env")
        return False

    try:
        bridge = LLMBridge(provider="gemini")

        # 1. List available models
        print("Available Gemini Models:")
        models = bridge.list_models()
        for m in models:
            if "gemini" in m:
                print(f"  - {m}")

        # 2. Test completion
        result = bridge.generate_text(
            system_prompt="You are a helpful assistant.",
            user_prompt="say ok",
        )
        print(f"Gemini ({bridge.model_name}) Response: {result}")
        return True
    except Exception as e:
        print(f"Gemini failed: {e}")
        return False


def test_deepseek():
    print("\n" + "=" * 10 + " Testing DeepSeek " + "=" * 10)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not found in .env")
        return False

    try:
        bridge = LLMBridge(provider="deepseek")

        # 1. List available models
        print("Available DeepSeek Models:")
        models = bridge.list_models()
        for m in models:
            print(f"  - {m}")

        # 2. Test completion
        result = bridge.generate_text(
            system_prompt="You are a helpful assistant.",
            user_prompt="say ok",
        )
        print(f"DeepSeek ({bridge.model_name}) Response: {result}")
        return True
    except Exception as e:
        print(f"DeepSeek failed: {e}")
        return False


if __name__ == "__main__":
    # Print key status
    oa_key = os.getenv("OPENAI_API_KEY")
    ge_key = os.getenv("GEMINI_API_KEY")
    ds_key = os.getenv("DEEPSEEK_API_KEY")
    print(
        f"Keys Status -> OpenAI: {'OK' if oa_key else 'Missing'}, "
        f"Gemini: {'OK' if ge_key else 'Missing'}, "
        f"DeepSeek: {'OK' if ds_key else 'Missing'}"
    )

    results = {
        "OpenAI": test_openai(),
        "Gemini": test_gemini(),
        "DeepSeek": test_deepseek(),
    }

    print("\n" + "=" * 36)
    passed = sum(results.values())
    if passed == len(results):
        print("RESULT: All brains are online!")
    elif passed > 0:
        online = [k for k, v in results.items() if v]
        print(f"RESULT: Partial success. Online: {', '.join(online)}")
    else:
        print("RESULT: Critical failure. Check API keys and network.")
