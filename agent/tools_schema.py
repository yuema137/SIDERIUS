import os
import json
from typing import List, Dict

def load_skills_from_library(skills_root: str = "skills") -> List[Dict]:
    """
    Dynamically scans the 'skills/' directory and loads all 'skill_config.json' files.
    This follows the pluggable 'Skills Library' architecture.
    """
    tools = []
    
    # Check if the skills directory exists
    if not os.path.exists(skills_root):
        print(f"Warning: Skills directory '{skills_root}' not found.")
        return tools

    # Iterate through each subfolder in the skills directory
    for skill_folder in os.listdir(skills_root):
        skill_path = os.path.join(skills_root, skill_folder)
        
        if os.path.isdir(skill_path):
            config_file = os.path.join(skill_path, "skill_config.json")
            
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        skill_metadata = json.load(f)
                        
                        # Wrap the metadata into the standard OpenAI Tool calling format
                        tool_definition = {
                            "type": "function",
                            "function": skill_metadata
                        }
                        tools.append(tool_definition)
                except Exception as e:
                    print(f"Error loading skill config from {skill_path}: {e}")
            else:
                print(f"Skipping {skill_folder}: No skill_config.json found.")
                
    return tools

# Globally accessible tools list for the LLM Bridge
# This will be populated at runtime when the agent starts
TIDMAD_TOOLS = load_skills_from_library()