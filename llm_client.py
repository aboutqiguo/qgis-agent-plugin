import os
import json
from openai import OpenAI

# Simple dotenv parser to avoid external dependencies
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
API_BASE = "https://api.deepseek.com"

if not API_KEY:
    print("Warning: DEEPSEEK_API_KEY not found in .env")

client = OpenAI(api_key=API_KEY, base_url=API_BASE)

def generate_pyqgis_code(user_prompt: str, context: str = "") -> str:
    """
    Calls DeepSeek API to generate PyQGIS code based on the user's prompt.
    """
    system_prompt = (
        "You are an expert GIS Developer specializing in QGIS 4.0 and PyQGIS.\n"
        "Your task is to write standalone PyQGIS Python scripts to solve the user's GIS problem.\n"
        "Return ONLY the Python code. Do not include markdown formatting or explanations.\n"
        "The code should assume `QgsApplication` is already initialized and the QGIS prefix path is set.\n"
        "Do NOT include `QgsApplication.setPrefixPath(...)` or `qgs = QgsApplication([], False)` in your code.\n"
        "Instead, write your logic inside a function `def execute_task():` and make sure it handles errors gracefully."
    )
    
    if context:
        system_prompt += f"\n\nReference PyQGIS 4.0 Documentation Context:\n{context}"
        
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print(f"Calling DeepSeek API... (Model: deepseek-chat)")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.1,
    )
    
    code = response.choices[0].message.content
    
    # Clean up markdown code blocks if the LLM output them
    code = code.strip()
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
        
    return code.strip()

if __name__ == '__main__':
    # A dry-run to check if API client initializes correctly. 
    # Not making actual API call to save user's balance.
    print("LLM Client initialized successfully.")
    print("DeepSeek API Key is loaded." if API_KEY else "DeepSeek API Key is MISSING.")
