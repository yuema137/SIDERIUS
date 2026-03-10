import os
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai

# Load the .env file
load_dotenv()

def test_openai():
    print("\n" + "="*10 + " Testing OpenAI " + "="*10)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in .env")
        return False
    
    try:
        client = OpenAI(api_key=api_key)
        
        # 1. List available models
        print("📋 Available OpenAI Models (Top 5):")
        models = client.models.list()
        # Sort and take top 5 for brevity
        for i, m in enumerate(sorted([m.id for m in models.data])):
            if i < 5: print(f"  - {m}")
        print(f"  ... (Total {len(models.data)} models found)")

        # 2. Test completion
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "say ok"}],
            max_tokens=5
        )
        print(f"✅ OpenAI Response: {response.choices[0].message.content.strip()}")
        return True
    except Exception as e:
        print(f"❌ OpenAI failed: {e}")
        return False

def test_gemini():
    print("\n" + "="*10 + " Testing Gemini " + "="*10)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not found in .env")
        return False
    
    try:
        genai.configure(api_key=api_key)
        
        # 1. List available models
        print("📋 Available Gemini Models:")
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"  - {m.name}")
                available_models.append(m.name)
        
        # 2. Test completion 
        # Using gemini-3-flash-preview as it's the one in your list
        target_model = 'gemini-3.1-flash-lite-preview'
        if f"models/{target_model}" not in available_models:
            # Fallback to the first available model if preview is missing
            target_model = available_models[0].split('/')[-1]
            
        model = genai.GenerativeModel(target_model)
        response = model.generate_content("say ok")
        print(f"✅ Gemini ({target_model}) Response: {response.text.strip()}")
        return True
    except Exception as e:
        print(f"❌ Gemini failed: {e}")
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
        print("RESULT: Both brains are online! 🚀")
    elif oa_res or ge_res:
        print("RESULT: Partial success. One brain is ready.")
    else:
        print("RESULT: Critical failure. Check API keys and network.")