import os
import json
import sys
import threading
from qgis.PyQt.QtCore import QThread, pyqtSignal
from openai import OpenAI

class HarnessThread(QThread):
    append_message_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()
    
    request_human_input_signal = pyqtSignal(str)
    request_destructive_auth_signal = pyqtSignal()
    request_plan_approval_signal = pyqtSignal()
    
    request_code_execution_signal = pyqtSignal(str)
    request_canvas_image_signal = pyqtSignal()
    request_atomic_tool_signal = pyqtSignal(str, dict)
    
    def __init__(self, plugin_dir, existing_messages=None, parent=None):
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        
        from .logger import get_logger
        self.logger = get_logger()
        self.logger.info("HarnessThread initialized.")
        
        self.user_input = ""
        self.model_name = "DeepSeek-Chat"
        self.work_mode = "PLAN"
        self.messages = existing_messages if existing_messages is not None else []
        self.plan_approved = False
        
        # Events for blocking thread while waiting for GUI
        self.human_input_event = threading.Event()
        self.human_input_response = ""
        
        self.plan_approval_event = threading.Event()
        self.plan_approval_response = ""
        
        self.code_exec_event = threading.Event()
        self.code_exec_response = ""
        
        self.destructive_auth_event = threading.Event()
        self.destructive_auth_response = False
        
        self.canvas_image_event = threading.Event()
        self.canvas_image_path = ""
        
        self.atomic_tool_event = threading.Event()
        self.atomic_tool_response = ""
        
        self.is_killed = False
        
        self.client = None
        self._init_client()
        
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_pyqgis_script",
                    "description": "Execute a Python script in the QGIS environment. You MUST provide complete, executable code. Do NOT output markdown formatting like ```python, ONLY output raw code.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "The raw Python code to execute. MUST be valid and complete. DO NOT use python formatting ticks."
                            },
                            "is_destructive": {
                                "type": "boolean",
                                "description": "Set to true if this code deletes, overwrites, or modifies existing user files on disk. Set to false if it only creates new files or modifies QGIS memory layers."
                            }
                        },
                        "required": ["code", "is_destructive"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_plan_for_approval",
                    "description": "Submit a proposed plan for human approval. Use this in PLAN mode after you output your detailed plan text.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_human",
                    "description": "Ask the human a clarifying question and wait for their response.",
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
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_vision_critic",
                    "description": "Capture the current QGIS map canvas as an image and send it to the GLM-4V-Flash vision model to get layout and cartographic advice.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "Specific questions to ask the vision model about the current map canvas (e.g., 'Where is the best empty space to place the legend?')"
                            }
                        },
                        "required": ["question"]
                    }
                }
            }
        ]
        
        from .tools import ATOMIC_TOOLS_SCHEMA
        self.tools.extend(ATOMIC_TOOLS_SCHEMA)
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "take_qgis_window_snapshot",
                "description": "Capture the entire QGIS window (including the map canvas, layer tree, and panels) to diagnose the UI state.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        })
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "update_agent_memory",
                "description": "Write a lesson learned or a user preference to the agent's long-term memory so you don't make the same mistake twice. Use this proactively when the user corrects your code or specifies a rule.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "description": "Must be 'global' (applies to all projects) or 'project' (specific to the current QGIS project)",
                            "enum": ["global", "project"]
                        },
                        "content": {
                            "type": "string",
                            "description": "The exact rule or lesson to append. Example: 'Do not use QgsComboBox, use QComboBox from qgis.PyQt.QtWidgets'"
                        }
                    },
                    "required": ["scope", "content"]
                }
            }
        })

    def _prepare_messages(self):
        from qgis.core import QgsSettings, QgsProject
        settings = QgsSettings()
        personality = settings.value("qgis_agent/agent_personality", "")
        global_memory = settings.value("qgis_agent/agent_memory", "")
        project_memory, _ = QgsProject.instance().readEntry("QGIS_Agent", "project_memory", "")

        base_prompt = "You are an advanced PyQGIS Agent. You can execute python code directly in the QGIS Python environment.\n"
        
        if personality:
            base_prompt += f"\n### [USER DEFINED PERSONALITY & RULES] ###\n{personality}\n"
        
        if global_memory or project_memory:
            base_prompt += "\n### 🧠 [YOUR LONG-TERM MEMORY & PREVIOUS LESSONS] ###\n"
            base_prompt += "These rules represent your past mistakes or user preferences. You MUST adhere to them.\n"
            if global_memory:
                base_prompt += f"\n-- Global Memory --\n{global_memory}\n"
            if project_memory:
                base_prompt += f"\n-- Current Project Memory --\n{project_memory}\n"
                
        base_prompt += """
- You MUST write complete, executable Python code.
- **SELF-CORRECTION & MEMORY**: If you execute code, encounter an error, and subsequently figure out how to fix it, you MUST call the `update_agent_memory` tool to write the lesson learned to your memory immediately! Do not just fix the code and move on; you must evolve.
- Always use `iface.messageBar().pushMessage()` to show progress to the human visually.
- IMPORTANT: Whenever you load, create, or process a new layer (vector or raster), you MUST add it to the QGIS project (`QgsProject.instance().addMapLayer(layer)`) or use `iface.addVectorLayer()` / `iface.addRasterLayer()` so the user can see the result on their screen! Do not just save files to disk silently.
"""
        import os
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.md")
        cheat_sheet = ""
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                cheat_sheet = f.read()
                
        base_prompt += "\n" + cheat_sheet + "\n"
        if self.work_mode == "PLAN":
            base_prompt += """
### ⚠️ CRITICAL WORKFLOW (PLAN MODE & ReAct)
1. **PLAN FIRST**: Do NOT call `execute_pyqgis_script` immediately. First, you MUST output a highly detailed, step-by-step text message explaining exactly what you plan to do. Use a Markdown checklist format (e.g., `- [ ] Step 1`).
2. **SUBMIT PLAN**: You MUST call `submit_plan_for_approval` IMMEDIATELY after outputting your text plan to pause execution and wait for human review. DO NOT just ask questions in text without calling the tool!
3. **RECENCY BIAS PROTECTION**: When the user provides feedback to modify your plan, you MUST retain the original overarching goal and merge the new feedback into a complete, updated checklist. Do NOT drop the original task!
4. **EXECUTE & VERIFY (ReAct)**: After the plan is approved, do NOT execute all steps in a single massive script! Execute ONE step at a time using your tools. After each step, verify the result, check off the item in your markdown list, and then proceed to the next step.
"""
        else:
            base_prompt += """
### 🟢 CRITICAL WORKFLOW (WORK MODE)
You are in auto-execute mode. You DO NOT need to submit plans for approval. You can directly call `execute_pyqgis_script` to fulfill the user's request immediately.
"""
        # Clean existing system prompts to avoid duplicates across restarts
        self.messages = [m for m in self.messages if m.get("role") != "system"]
        self.messages.insert(0, {"role": "system", "content": base_prompt})

    def _get_qgis_context(self):
        try:
            from qgis.core import QgsProject
            import os
            context_str = "### CURRENT QGIS ENVIRONMENT CONTEXT ###\n"
            layers = QgsProject.instance().mapLayers()
            if not layers:
                context_str += "- Loaded Map Layers: None\n"
            else:
                context_str += "- Loaded Map Layers:\n"
                for layer_id, layer in layers.items():
                    context_str += f"  * {layer.name()}\n"
                    
            home = QgsProject.instance().homePath()
            if home and os.path.exists(home):
                context_str += f"- Project Home Directory ({home}) contains:\n"
                try:
                    files = os.listdir(home)
                    context_str += f"  {', '.join(files[:30])}\n"
                except:
                    pass
            return context_str
        except Exception:
            return "### CURRENT QGIS ENVIRONMENT CONTEXT ###\n(Context unavailable)"
        
    def _process_mentions(self, text):
        import re
        from qgis.core import QgsProject
        
        mentions = re.findall(r'@([^\s]+)', text)
        if not mentions:
            return ""
            
        context = []
        layers = QgsProject.instance().mapLayers().values()
        
        for mention in mentions:
            mention_lower = mention.lower()
            matched_layer = None
            for layer in layers:
                if mention_lower in layer.name().lower():
                    matched_layer = layer
                    break
                    
            if matched_layer:
                crs = matched_layer.crs()
                crs_info = crs.authid() if crs.isValid() else "Invalid/None"
                bbox = matched_layer.extent().toString()
                source = matched_layer.source()
                context.append(f"- Layer '{matched_layer.name()}': CRS={crs_info}, Extent={bbox}, Path={source}")
                
        return "\n".join(context)

    def _init_client(self):
        from qgis.core import QgsSettings
        s = QgsSettings()
        api_key = s.value("qgis_agent/deepseek_api_key", "")
        base_url = s.value("qgis_agent/deepseek_base_url", "https://api.deepseek.com")
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.logger.error("DeepSeek API Key not configured in Settings.")
            self.append_message_signal.emit("SYSTEM", "Error: DeepSeek API Key not configured. Please open Settings (⚙️).")
            self.finished_signal.emit()
            return

    def run(self):
        if not getattr(self, 'client', None):
            self.logger.error("Client not initialized. API Key missing.")
            self.finished_signal.emit()
            return
            
        self.logger.info(f"User Input: {self.user_input}")
        
        # Process @ mentions
        self.ghost_context = self._process_mentions(self.user_input)
        if self.ghost_context:
            self.logger.info(f"Injected Ghost Context:\n{self.ghost_context}")
            
        # Process IMAGE_ATTACHMENT
        import re
        img_match = re.search(r"\[IMAGE_ATTACHMENT\](.*)", self.user_input)
        if img_match:
            img_path = img_match.group(1).strip()
            self.append_message_signal.emit("SYSTEM", "✨ 正在将附带的截图发给视觉大模型进行预处理...")
            import time; time.sleep(0.1)
            import base64, requests
            try:
                with open(img_path, "rb") as f:
                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                from qgis.core import QgsSettings
                glm_key = QgsSettings().value("qgis_agent/glm_api_key", "")
                glm_base_url = QgsSettings().value("qgis_agent/glm_base_url", "https://open.bigmodel.cn/api/paas/v4")
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {glm_key}"
                }
                user_prompt = self.user_input.replace(img_match.group(0), "")
                glm_vision_model = QgsSettings().value("qgis_agent/glm_vision_model", "glm-4v-flash")
                payload = {
                    "model": glm_vision_model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Please provide a detailed description of this image. The user attached it to a QGIS Copilot session with the following prompt:\n'{user_prompt}'"},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                        ]
                    }]
                }
                resp = requests.post(f"{glm_base_url}/chat/completions", headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    vision_desc = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                    self.user_input = self.user_input.replace(img_match.group(0), f"\n\n[Vision Model Analysis of User's Attached Image]:\n{vision_desc}")
                    self.logger.info("Successfully converted image to text description via GLM.")
                else:
                    self.user_input = self.user_input.replace(img_match.group(0), f"\n\n[Error analyzing image: {resp.status_code}]")
            except Exception as e:
                self.user_input = self.user_input.replace(img_match.group(0), f"\n\n[Exception analyzing image: {str(e)}]")
            
        self._prepare_messages()
        self.messages.append({"role": "user", "content": self.user_input})
        
        try:
            while True:
                if self.is_killed:
                    self.logger.info("Agent thread was killed by user.")
                    self.append_message_signal.emit("SYSTEM", "🛑 Operation stopped by user.")
                    break
                    
                self.append_message_signal.emit("SYSTEM", "Thinking...")
                
                # Inject dynamic QGIS context into the messages before sending
                messages_to_send = self.messages.copy()
                dynamic_context = self._get_qgis_context()
                if getattr(self, "ghost_context", None):
                    dynamic_context += "\n\n[System Auto-Injected Context based on @ Mentions]:\n" + self.ghost_context
                messages_to_send.append({"role": "system", "content": dynamic_context})
                
                real_model_name = self.model_name.split(" ")[0]
                
                kwargs = {
                    "model": real_model_name,
                    "messages": messages_to_send,
                }
                import json
                
                # Apply thinking and reasoning_effort for DeepSeek models
                if "deepseek" in real_model_name:
                    if "Disabled" in self.effort_level:
                        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                    elif "Max" in self.effort_level:
                        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                        kwargs["reasoning_effort"] = "max"
                    else: # High (default)
                        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                        kwargs["reasoning_effort"] = "high"
                
                # In DeepSeek V4 API, both Flash and Pro support native tool calling!
                # Keep the fallback ONLY for the deprecated "deepseek-reasoner" alias if someone forces it.
                if real_model_name != "deepseek-reasoner":
                    kwargs["tools"] = self.tools
                    kwargs["tool_choice"] = "auto"
                else:
                    tools_desc = json.dumps([t['function'] for t in self.tools], indent=2, ensure_ascii=False)
                    reasoner_sys = (
                        "You are currently DeepSeek-Reasoner. The native Tool calling API is disabled. "
                        "However, you MUST use the following tools manually to interact with the QGIS environment:\n\n"
                        f"{tools_desc}\n\n"
                        "To call a tool (like `download_osm_data` or `create_geodatabase`), you MUST output a JSON block like this:\n"
                        "```json\n{\n  \"tool_name\": \"name_of_tool\",\n  \"arguments\": {\n    \"arg1\": \"value1\"\n  }\n}\n```\n"
                        "For writing arbitrary Python scripts, you can simply output a ```python ... ``` block, which will automatically trigger the `execute_pyqgis_script` tool."
                    )
                    messages_to_send.append({"role": "system", "content": reasoner_sys})
                    
                response = self.client.chat.completions.create(**kwargs)
                
                msg = response.choices[0].message
                msg_dict = msg.model_dump(exclude_none=True)
                
                # Check for reasoning_content (R1)
                reasoning_content = getattr(msg, "reasoning_content", None)
                if reasoning_content:
                    formatted_reasoning = f'<div style="color: #666; background-color: #f8f9fa; padding: 10px; border-left: 3px solid #007bff; margin: 5px 0; font-size: 12px;"><b>🧠 思考过程:</b><br/><pre style="white-space: pre-wrap; margin: 0; font-family: monospace;">{reasoning_content}</pre></div>'
                    self.append_message_signal.emit("SYSTEM", formatted_reasoning)
                    msg_dict["reasoning_content"] = reasoning_content
                
                # Manual tool parsing for reasoner
                if self.model_name == "deepseek-reasoner" and msg.content:
                    import re, uuid
                    
                    mock_tool_calls = []
                    
                    # 1. Parse JSON tool calls
                    json_blocks = re.findall(r'```json\n(.*?)\n```', msg.content, re.DOTALL)
                    for j_block in json_blocks:
                        try:
                            parsed_j = json.loads(j_block)
                            if "tool_name" in parsed_j and "arguments" in parsed_j:
                                mock_tool_calls.append({
                                    "id": f"call_{uuid.uuid4().hex[:10]}",
                                    "type": "function",
                                    "function": {
                                        "name": parsed_j["tool_name"],
                                        "arguments": json.dumps(parsed_j["arguments"])
                                    }
                                })
                        except Exception as e:
                            self.logger.warning(f"Failed to parse JSON tool block: {e}")
                            
                    # 2. Parse Python blocks
                    py_blocks = re.findall(r'```python\n(.*?)\n```', msg.content, re.DOTALL)
                    for code in py_blocks:
                        mock_tool_calls.append({
                            "id": f"call_{uuid.uuid4().hex[:10]}",
                            "type": "function",
                            "function": {
                                "name": "execute_pyqgis_script",
                                "arguments": json.dumps({"code": code, "is_destructive": False})
                            }
                        })
                        
                    if mock_tool_calls:
                        msg_dict["tool_calls"] = mock_tool_calls
                        self.logger.info(f"Auto-parsed {len(mock_tool_calls)} tool_calls for deepseek-reasoner.")
                
                self.messages.append(msg_dict)
                
                if msg.content:
                    self.logger.info(f"Agent text response: {msg.content}")
                    self.append_message_signal.emit("AGENT", msg.content)
                
                # Use msg_dict for tool_calls check
                # Re-wrap msg_dict to an object-like wrapper for the rest of the loop
                class MsgWrapper:
                    def __init__(self, d):
                        self.content = d.get("content")
                        self.tool_calls = d.get("tool_calls")
                        
                msg_wrapped = MsgWrapper(msg_dict)
                
                if not getattr(msg_wrapped, "tool_calls", None):
                    # Fallback: if the model forgot to use the tool API but output a python block anyway
                    import re, uuid
                    py_blocks = re.findall(r'```python\n(.*?)\n```', msg.content or "", re.DOTALL)
                    if py_blocks:
                        code = py_blocks[0]
                        mock_tc = {
                            "id": f"call_{uuid.uuid4().hex[:10]}",
                            "type": "function",
                            "function": {
                                "name": "execute_pyqgis_script",
                                "arguments": json.dumps({"code": code, "is_destructive": False})
                            }
                        }
                        msg_dict["tool_calls"] = [mock_tc]
                        msg_wrapped.tool_calls = [mock_tc]
                        self.logger.info("Auto-parsed python block into tool_calls for model that forgot tool API.")
                    elif self.work_mode == "PLAN" and not getattr(self, "plan_approved", False):
                        # The model is in PLAN mode, hasn't approved a plan yet, and outputted text without calling submit_plan_for_approval.
                        # Forcefully wrap it in a submit_plan_for_approval tool call!
                        mock_tc = {
                            "id": f"call_{uuid.uuid4().hex[:10]}",
                            "type": "function",
                            "function": {
                                "name": "submit_plan_for_approval",
                                "arguments": "{}"
                            }
                        }
                        msg_dict["tool_calls"] = [mock_tc]
                        msg_wrapped.tool_calls = [mock_tc]
                        self.logger.info("Auto-injected submit_plan_for_approval because model forgot to call it.")
                    else:
                        self.logger.info("Agent stopped without tool calls. Yielding turn to user.")
                        break
                
                # We do not use else because if the fallback triggered, we want to execute the tool
                self._consecutive_no_tool = 0
                    
                for tc_dict in msg_wrapped.tool_calls:
                    # Create a mock tool_call object for the inner loop
                    class ToolCallWrapper:
                        def __init__(self, t):
                            self.id = t["id"]
                            self.function = lambda: None
                            self.function.name = t["function"]["name"]
                            self.function.arguments = t["function"]["arguments"]
                    tool_call = ToolCallWrapper(tc_dict)
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    
                    if name == "ask_human":
                        question = args.get("question", "")
                        self.logger.info(f"Agent asking human: {question}")
                        self.human_input_event.clear()
                        self.request_human_input_signal.emit(question)
                        # Block thread until GUI signals back
                        self.human_input_event.wait()
                        
                        answer = self.human_input_response
                        self.logger.info(f"Human answered: {answer}")
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": answer
                        })
                        
                    elif name == "ask_vision_critic":
                        question = args.get("question", "")
                        self.logger.info(f"Asking vision critic: {question}")
                        self.canvas_image_event.clear()
                        self.request_canvas_image_signal.emit()
                        self.canvas_image_event.wait()
                        
                        img_path = self.canvas_image_path
                        result = ""
                        if not img_path or not os.path.exists(img_path):
                            result = "Error: Could not capture map canvas."
                        else:
                            import base64
                            import requests
                            try:
                                with open(img_path, "rb") as f:
                                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                                
                                from qgis.core import QgsSettings
                                glm_key = QgsSettings().value("qgis_agent/glm_api_key", "")
                                headers = {
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {glm_key}"
                                }
                                glm_vision_model = QgsSettings().value("qgis_agent/glm_vision_model", "glm-4v-flash")
                                payload = {
                                    "model": glm_vision_model,
                                    "messages": [{
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": question},
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                                        ]
                                    }]
                                }
                                self.append_message_signal.emit("SYSTEM", "👀 正在呼叫 GLM-4V 视觉排版顾问...")
                                import time; time.sleep(0.1)
                                resp = requests.post(f"{glm_base_url}/chat/completions", headers=headers, json=payload, timeout=30)
                                if resp.status_code == 200:
                                    result = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                                    self.append_message_signal.emit("SYSTEM", f"GLM 顾问反馈: {result}")
                                else:
                                    result = f"Vision API Error: {resp.status_code} - {resp.text}"
                            except Exception as e:
                                result = f"Vision API Exception: {str(e)}"
                                
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })

                    elif name == "update_agent_memory":
                        scope = args.get("scope", "global")
                        content = args.get("content", "")
                        self.logger.info(f"Agent updating memory ({scope}): {content}")
                        
                        from qgis.core import QgsSettings, QgsProject
                        if scope == "global":
                            settings = QgsSettings()
                            current_mem = settings.value("qgis_agent/agent_memory", "")
                            new_mem = current_mem + f"\n- {content}" if current_mem else f"- {content}"
                            settings.setValue("qgis_agent/agent_memory", new_mem)
                            result = "Global memory successfully updated."
                        else:
                            prj = QgsProject.instance()
                            current_mem, _ = prj.readEntry("QGIS_Agent", "project_memory", "")
                            new_mem = current_mem + f"\n- {content}" if current_mem else f"- {content}"
                            prj.writeEntry("QGIS_Agent", "project_memory", new_mem)
                            result = "Project memory successfully updated."
                            
                        self.append_message_signal.emit("SYSTEM", f"🧠 记忆已进化 ({scope}): {content}")
                        
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })

                    elif name in ["list_layers", "zoom_to_layer", "set_layer_visibility", "take_qgis_window_snapshot", "inspect_layer_fields", "get_selected_features", "select_features_by_expression", "clear_selection", "zoom_to_selected", "run_processing_algorithm", "create_geodatabase", "query_pyqgis_doc", "download_osm_data"]:
                        self.logger.info(f"Executing atomic tool: {name}")
                        self.atomic_tool_event.clear()
                        self.request_atomic_tool_signal.emit(name, args)
                        self.atomic_tool_event.wait()
                        result = self.atomic_tool_response
                        
                        if result.startswith("[IMAGE_PATH]"):
                            img_path = result.replace("[IMAGE_PATH]", "")
                            import base64, requests
                            try:
                                with open(img_path, "rb") as f:
                                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                                from qgis.core import QgsSettings
                                glm_key = QgsSettings().value("qgis_agent/glm_api_key", "")
                                glm_base_url = QgsSettings().value("qgis_agent/glm_base_url", "https://open.bigmodel.cn/api/paas/v4")
                                headers = {
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {glm_key}"
                                }
                                glm_vision_model = QgsSettings().value("qgis_agent/glm_vision_model", "glm-4v-flash")
                                payload = {
                                    "model": glm_vision_model,
                                    "messages": [{
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": "Please analyze this QGIS screenshot in detail. Describe the layers, the canvas, and any open panels/dialogs."},
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                                        ]
                                    }]
                                }
                                self.append_message_signal.emit("SYSTEM", "✨ 正在将附带的截图发给视觉大模型进行预处理...")
                                import time; time.sleep(0.1)
                                resp = requests.post(f"{glm_base_url}/chat/completions", headers=headers, json=payload, timeout=30)
                                if resp.status_code == 200:
                                    result = "Screenshot analysis from Vision Model:\n" + resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                                else:
                                    result = f"Vision API Error: {resp.status_code} - {resp.text}"
                            except Exception as e:
                                result = f"Vision API Exception: {str(e)}"
                                
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })

                    elif name == "submit_plan_for_approval":
                        self.logger.info("Agent requesting plan approval.")
                        self.plan_approval_event.clear()
                        self.request_plan_approval_signal.emit()
                        # Block thread
                        self.plan_approval_event.wait()
                        if self.is_killed: break
                        
                        action = self.plan_approval_response
                        self.logger.info(f"User plan action: {action}")
                        
                        if action == "REJECT":
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": name,
                                "content": "Plan rejected by user. Please revise the plan or ask for clarification."
                            })
                            continue
                        elif action.startswith("REVISE:"):
                            feedback = action.replace("REVISE:", "").strip()
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": name,
                                "content": f"User provided modification feedback for your plan: '{feedback}'. Please update your plan immediately incorporating this feedback, while STRICTLY RETAINING the original overarching goal."
                            })
                            continue
                        else:
                            self.plan_approved = True
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": name,
                                "content": "Plan approved. Proceed to execute."
                            })
                            
                    elif name == "execute_pyqgis_script":
                        if self.work_mode == "PLAN" and not self.plan_approved:
                            error_msg = "Error: You are in PLAN mode. You MUST call submit_plan_for_approval and wait for human approval BEFORE executing any code."
                            self.logger.warning(f"Agent violated PLAN mode constraints.")
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": name,
                                "content": error_msg
                            })
                            continue
                            
                        code = args.get("code", "")
                        is_destructive = args.get("is_destructive", False)
                        
                        self.logger.debug(f"Agent attempting to execute code (Destructive: {is_destructive}):\n{code}")
                        
                        if is_destructive:
                            self.logger.warning("Agent requested destructive auth.")
                            self.destructive_auth_event.clear()
                            self.request_destructive_auth_signal.emit()
                            self.destructive_auth_event.wait()
                            
                            if not self.destructive_auth_response:
                                self.logger.warning("User denied destructive operation.")
                                self.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": name,
                                    "content": "Error: User denied the destructive operation."
                                })
                                continue
                                
                        self.append_message_signal.emit("SYSTEM", f"Agent generated and is executing the following code:\n<pre>{code}</pre>")
                        
                        # Request execution on the main thread to ensure GUI safety
                        self.code_exec_event.clear()
                        self.request_code_execution_signal.emit(code)
                        self.code_exec_event.wait()
                        if self.is_killed: break
                        
                        output = self.code_exec_response
                        self.logger.info(f"Execution Result:\n{output}")
                        self.append_message_signal.emit("SYSTEM", f"Execution Result:\n{output}")
                        
                        # Phase 17: Self-Healing
                        break_outer_loop = False
                        if "Error executing script:" in output or "Traceback " in output or output.startswith("Error"):
                            self._error_retries = getattr(self, "_error_retries", 0) + 1
                            if self._error_retries >= 3:
                                self.append_message_signal.emit("SYSTEM", "⚠️ Max error retries (3) reached. Yielding to user.")
                                self.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": name,
                                    "content": output
                                })
                                self._error_retries = 0
                                break_outer_loop = True
                                break
                            else:
                                output = output + f"\n\n[SYSTEM] Execution failed. You have {3 - self._error_retries} retries left. Please analyze the Traceback and fix the code."
                        else:
                            self._error_retries = 0
                        
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": output
                        })
                        
                if locals().get("break_outer_loop", False):
                    break
                        
        except Exception as e:
            self.logger.error(f"Exception during Agent execution: {str(e)}", exc_info=True)
            self.append_message_signal.emit("SYSTEM", f"Exception during Agent execution: {str(e)}")
            
        self.finished_signal.emit()

    # Callbacks from main thread
    def provide_human_input(self, answer):
        self.human_input_response = answer
        self.human_input_event.set()
        
    def provide_destructive_auth(self, is_approved):
        self.destructive_auth_response = is_approved
        self.destructive_auth_event.set()
