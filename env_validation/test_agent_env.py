import os
from dotenv import load_dotenv
from agent.llm_bridge import LLMBridge

# Load the .env file
load_dotenv()

def test_openai():
    print("\n" + "="*10 + " Testing OpenAI " + "="*10)
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
    print("\n" + "="*10 + " Testing Gemini " + "="*10)
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

if __name__ == "__main__":
    # Print key status
    oa_key = os.getenv("OPENAI_API_KEY")
    ge_key = os.getenv("GEMINI_API_KEY")
    print(f"Keys Status -> OpenAI: {'OK' if oa_key else 'Missing'}, Gemini: {'OK' if ge_key else 'Missing'}")

    oa_res = test_openai()
    ge_res = test_gemini()

    print("\n" + "="*36)
    if oa_res and ge_res:
        print("RESULT: Both brains are online!")
    elif oa_res or ge_res:
        print("RESULT: Partial success. One brain is ready.")
    else:
        print("RESULT: Critical failure. Check API keys and network.")
