# agent/llm_bridge.py

import os
import json
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from openai import OpenAI
from dotenv import load_dotenv

# Import the new prompt generators from agent/prompts.py
from agent.prompts import (
    PLANNER_PROMPT, 
    REFLECTOR_PROMPT, 
    get_planner_user_prompt, 
    get_reflector_user_prompt
)

class LLMBridge:
    def __init__(self, provider: str = "gemini", model_id: Optional[str] = None):
        """
        Initializes the LLM bridge. 
        Optimized for Gemini 3 Flash and Research Memory logic.
        """
        load_dotenv()
        self.provider = provider.lower()
        
        if self.provider == "gemini":
            self.api_key = os.getenv("GEMINI_API_KEY")
            genai.configure(api_key=self.api_key)
            # Using Gemini 3 Flash for fast inference and native JSON support
            self.model_name = model_id if model_id else "gemini-3-flash"
        elif self.provider == "openai":
            self.api_key = os.getenv("OPENAI_API_KEY")
            self.client = OpenAI(api_key=self.api_key)
            self.model_name = model_id if model_id else "gpt-4o"
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def plan(self, 
             memory_history: List[Dict], 
             expert_advice: str = "None", 
             force_model: str = "auto",
             config_manual: Optional[Dict] = None) -> Dict:
        """
        Uses the Planner logic to observe Research Memory and decide next steps.
        Incorporates physical constraints from config_manual to prevent hallucinations.
        """
        system_prompt = PLANNER_PROMPT
        
        # --- 2. Inject config manual ---
        manual_context = ""
        if config_manual:
            manual_context = f"\n\n[STRICT PHYSICAL CONSTRAINTS / CONFIG MANUAL]:\n{json.dumps(config_manual, indent=2)}"
        
        # Pass the new arguments to the prompt generator
        user_prompt = get_planner_user_prompt(
            memory_history=memory_history, 
            expert_advice=expert_advice, 
            force_model=force_model
        )
        
        # pass the manual into prompt
        final_user_prompt = user_prompt + manual_context
        
        return self._generate_json_response(system_prompt, final_user_prompt)
        
    def reflect(self, exp_id: str, hypothesis: str, actual_results: Dict) -> Dict:
        """
        Uses the Reflector logic to transform results into new Memory entries.
        """
        system_prompt = REFLECTOR_PROMPT
        user_prompt = get_reflector_user_prompt(exp_id, hypothesis, actual_results)
        
        return self._generate_json_response(system_prompt, user_prompt)

    def _generate_json_response(self, system_prompt: str, user_prompt: str) -> Dict:
        """
        Internal helper to get strictly formatted JSON from LLM.
        Uses native JSON modes for both Gemini and OpenAI.
        """
        if self.provider == "gemini":
            # Gemini 3 Flash native JSON mode
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt
            )
            response = model.generate_content(
                user_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            try:
                # Basic cleanup in case of markdown blocks, though response_mime_type usually handles it
                text = response.text.strip()
                if text.startswith("```json"):
                    text = text[7:-3]
                return json.loads(text)
            except json.JSONDecodeError:
                print(f"🚨 Failed to parse Gemini JSON: {response.text}")
                return {}

        elif self.provider == "openai":
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)

    def request(self, system_prompt: str, messages: List[Dict], tools: List[Dict]) -> Any:
        """Standard tool-calling interface for backward compatibility with other skills."""
        if self.provider == "openai":
            full_messages = [{"role": "system", "content": system_prompt}] + messages
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=full_messages,
                tools=tools,
                tool_choice="auto"
            )
            return response.choices[0].message
        
        elif self.provider == "gemini":
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
                tools=tools
            )
            response = model.generate_content(messages[-1]["content"])
            return response