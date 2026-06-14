import os
import json
from openai import OpenAI
from qgis_executor import execute_pyqgis_code
import agent  # For retrieve_context

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
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_pyqgis_script",
            "description": "Executes PyQGIS code in the QGIS sandbox. Use this to perform GIS analysis, mapping, and file operations. You can import qgis_tools for simplified wrappers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The PyQGIS python code. Must include a 'def execute_task():' function. You MUST add `import sys; sys.path.append(r'D:\\project\\QGIS开发')` before importing qgis_tools."
                    },
                    "is_destructive": {
                        "type": "boolean",
                        "description": "Set to true if this code overwrites or deletes existing files."
                    }
                },
                "required": ["code", "is_destructive"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ask_human",
            "description": "Ask the human user a question to clarify ambiguity, request parameters, or ask for visual confirmation (e.g. asking if a rendered map looks good).",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user."
                    }
                },
                "required": ["question"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are a highly capable PyQGIS 4.0 Agent. 
You can execute PyQGIS code and interact with the user.
To save tokens, you MUST use the provided `qgis_tools` Python library when writing code, instead of raw QGIS API if possible.
Available in `qgis_tools`:
- io_tools: load_vector_layer(path, layer_name=None), load_raster_layer(path), save_layer(layer, output_path)
- geoprocessing_tools: buffer(layer, distance, output_path="memory:"), clip(input_layer, overlay_layer, output_path)
- mapping_tools: render_quick_map(output_path, layers=None)

Example usage in code:
```python
import sys
sys.path.append(r'D:\project\QGIS开发')
from qgis_tools import load_vector_layer, buffer, render_quick_map

def execute_task():
    layer = load_vector_layer('my_data.shp')
    buf_layer = buffer(layer, 100.0)
    render_quick_map('map.png', [buf_layer, layer])
```

IMPORTANT:
- If a user prompt is ambiguous (e.g., missing buffer distance), call `ask_human`.
- Before making permanent file changes, ensure `is_destructive` is True in your tool call.
- After generating a map, you might want to call `ask_human` to ask if they want adjustments.
"""

class AgentHarness:
    def __init__(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def chat(self, user_input: str):
        # Retrieve context if needed
        context = agent.retrieve_context(user_input)
        if context:
            user_input += f"\n\n[Reference Docs]:\n{context}"
            
        self.messages.append({"role": "user", "content": user_input})
        
        while True:
            print("[AGENT]: Thinking...")
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=self.messages,
                    tools=TOOLS,
                    temperature=0.1
                )
            except Exception as e:
                return f"API Error: {e}"
            
            msg = response.choices[0].message
            
            # The API returns message objects, append it
            self.messages.append(msg)
            
            if not msg.tool_calls:
                # LLM just responded with text
                return msg.content
                
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except Exception as e:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": f"Failed to parse arguments: {e}"
                    })
                    continue
                
                if name == "ask_human":
                    question = args.get("question", "No question provided.")
                    print(f"\n[AGENT QUESTION]: {question}")
                    answer = input("[USER ANSWER]: ")
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": answer
                    })
                    
                elif name == "execute_pyqgis_script":
                    code = args.get("code", "")
                    is_destructive = args.get("is_destructive", False)
                    
                    if is_destructive:
                        print("\n[WARNING]: Agent wants to perform a destructive file operation.")
                        confirm = input("Approve? (y/n): ")
                        if confirm.lower() != 'y':
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": name,
                                "content": "Error: User denied the destructive operation. Please adjust your plan or output to a memory layer."
                            })
                            continue
                            
                    print("\n[AGENT]: Executing PyQGIS script via sandbox...")
                    output = execute_pyqgis_code(code)
                    print(f"Result:\n{output}")
                    
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": name,
                        "content": output
                    })
