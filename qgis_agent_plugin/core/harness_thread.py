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
    request_destructive_auth_signal = pyqtSignal(str)
    request_plan_approval_signal = pyqtSignal()
    
    request_code_execution_signal = pyqtSignal(str)
    request_canvas_image_signal = pyqtSignal()
    request_atomic_tool_signal = pyqtSignal(str, dict)
    
    def __init__(self, plugin_dir, existing_messages=None, parent=None):
        super().__init__(parent)
        self.plugin_dir = plugin_dir
        
        from ..utils.logger import get_logger
        self.logger = get_logger()
        self.logger.info("HarnessThread initialized.")
        
        self.user_input = ""
        self.model_name = "DeepSeek-Chat"
        self.effort_level = "High"
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
                    "description": "Submit a proposed plan for human approval. You MUST pass your detailed plan text and checklist into the 'plan_markdown' argument.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "plan_markdown": {"type": "string", "description": "The full markdown content of your plan and checklist. Use [ ], [/], [x]."}
                        },
                        "required": ["plan_markdown"]
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
        
        from ..tools.tools import ATOMIC_TOOLS_SCHEMA
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
                "name": "read_file",
                "description": "Read the contents of a local file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file."}
                    },
                    "required": ["file_path"]
                }
            }
        })
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write text content to a local file (overwrites existing).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file."},
                        "content": {"type": "string", "description": "The text content to write."}
                    },
                    "required": ["file_path", "content"]
                }
            }
        })
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "replace_file_content",
                "description": "Replace a specific substring in a local file with new content. Useful for checking off items in task.md.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Absolute path to the file."},
                        "target_content": {"type": "string", "description": "The exact string to be replaced."},
                        "replacement_content": {"type": "string", "description": "The new string to insert."}
                    },
                    "required": ["file_path", "target_content", "replacement_content"]
                }
            }
        })
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "save_skill",
                "description": "Save a reusable, successful PyQGIS snippet to your Procedural Skills library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "A short, unique filename for the skill (e.g., 'buffer_and_clip')."},
                        "description": {"type": "string", "description": "A detailed description of what the skill does and what inputs it expects."},
                        "python_code": {"type": "string", "description": "The complete, working PyQGIS Python code to save."}
                    },
                    "required": ["skill_name", "description", "python_code"]
                }
            }
        })
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "search_skills",
                "description": "Search your Procedural Skills library for previously saved scripts.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keywords (e.g., 'buffer', 'network analysis')."}
                    },
                    "required": ["query"]
                }
            }
        })
        
        self.tools.append({
            "type": "function",
            "function": {
                "name": "search_past_conversations",
                "description": "Search past conversation history from the SQLite Episodic Memory database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keywords to search in previous chats or tool outputs."}
                    },
                    "required": ["query"]
                }
            }
        })

    def _prepare_messages(self):
        from qgis.core import QgsSettings, QgsProject
        settings = QgsSettings()
        personality = settings.value("qgis_agent/agent_personality", "")
        project_home = QgsProject.instance().homePath()

        base_prompt = "You are an advanced PyQGIS Agent. You can execute python code directly in the QGIS Python environment.\n"
        
        if personality:
            base_prompt += f"\n### [USER DEFINED PERSONALITY & RULES] ###\n{personality}\n"
        
        # Inject Durable Curated Memory (Hermes Architecture)
        base_prompt += "\n### 🧠 [DURABLE CURATED MEMORY] ###\n"
        base_prompt += "These markdown files represent your long-term memory. You MUST adhere to the rules within them.\n"
        base_prompt += "If you learn new facts, environment quirks, or user preferences, you MUST proactively use the `write_file` or `replace_file_content` tools to update these files so you don't forget!\n\n"
        
        import os
        user_md_path = os.path.join(self.plugin_dir, "USER.md")
        
        if os.path.exists(user_md_path):
            with open(user_md_path, "r", encoding="utf-8") as f:
                base_prompt += f"-- USER.md (Global User Preferences/Facts, Absolute Path: `{user_md_path}`) --\n{f.read()}\n\n"
        else:
            base_prompt += f"-- USER.md --\n(No global preferences recorded yet. You can create this file using `write_file` at its absolute path: `{user_md_path}`)\n\n"
            
        if project_home:
            memory_md_path = os.path.join(project_home, "MEMORY.md")
            
            if os.path.exists(memory_md_path):
                with open(memory_md_path, "r", encoding="utf-8") as f:
                    base_prompt += f"-- MEMORY.md (Project Facts & Quirks, Absolute Path: `{memory_md_path}`) --\n{f.read()}\n\n"
            else:
                base_prompt += f"-- MEMORY.md --\n(No project facts recorded yet. You can create this file using `write_file` at its absolute path: `{memory_md_path}`)\n\n"
        import os
        base_dir = os.path.dirname(os.path.dirname(__file__))
        
        # 1. Scan and build skill manifest
        skill_manifest = "可用技能目录:\n"
        skills_core_dir = os.path.join(base_dir, "skills", "core")
        skills_dyn_dir = os.path.join(base_dir, "skills", "dynamic")
        
        for d in [skills_core_dir, skills_dyn_dir]:
            if os.path.exists(d):
                for f_name in os.listdir(d):
                    if f_name.endswith('.md'):
                        try:
                            with open(os.path.join(d, f_name), 'r', encoding='utf-8') as sf:
                                content = sf.read()
                                import re
                                name_match = re.search(r'<name>(.*?)</name>', content, re.DOTALL)
                                desc_match = re.search(r'<description>(.*?)</description>', content, re.DOTALL)
                                if name_match and desc_match:
                                    skill_manifest += f"- `{name_match.group(1).strip()}`: {desc_match.group(1).strip()}\n"
                        except Exception:
                            pass
        
        # 2. Load core system prompt
        prompt_path = os.path.join(base_dir, "prompts", "system_prompt.md")
        cheat_sheet = ""
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                cheat_sheet = f.read().replace("{skill_directory}", skill_manifest)
                
        base_prompt += "\n" + cheat_sheet + "\n"
        if self.work_mode == "PLAN":
            base_prompt += """
### ⚠️ CRITICAL WORKFLOW (PLAN MODE & ARTIFACT TRACKING)
1. **PLAN FIRST**: Do NOT call `execute_pyqgis_script` to solve the problem immediately! First, you MUST formulate a detailed plan and a markdown checklist of steps. 
   - ⚠️ FORMAT: Your markdown checklist MUST strictly follow this format, using proper bullet points (`- `) and a main header:
     # 任务执行进度
     
     - [ ] 步骤1：...
     - [ ] 步骤2：...
   - ⚠️ CRITICAL: Your initially proposed plan MUST have ALL steps marked as pending `[ ]`. Do NOT mark any step as completed `[x]` before you have actually executed the code for it!
2. **SUBMIT PLAN**: You MUST call `submit_plan_for_approval` and pass your full markdown plan into the 'plan_markdown' argument. This will automatically save it to `task.md` and pause execution for human review. DO NOT proceed without calling this tool!
3. **EXECUTE & VERIFY (ReAct)**: Once the user approves, execute ONE step at a time using `execute_pyqgis_script`. To save tokens, you don't need to update `task.md` after every single minor tool call. However, you MUST use `replace_file_content` to update the checkboxes (e.g., `[x]`) in `task.md` before you finish your turn (when you are about to stop calling tools and reply to the user).
4. **WALKTHROUGH**: After all steps are completed, create a `walkthrough.md` summarizing what you accomplished.
"""
        else:
            base_prompt += """
### 🟢 CRITICAL WORKFLOW (WORK MODE)
You are in auto-execute mode. You DO NOT need to submit plans for approval. You can directly call `execute_pyqgis_script` to fulfill the user's request immediately.
"""
        # Clean existing system prompts to avoid duplicates across restarts
        self.messages[:] = [m for m in self.messages if m.get("role") != "system"]
        
        # Self-heal corrupted memory from huge outputs that crash the LLM API
        for m in self.messages:
            if isinstance(m.get("content"), str) and len(m["content"]) > 15000:
                original_len = len(m["content"])
                m["content"] = m["content"][:5000] + f"\n\n...[Output middle truncated! Original length: {original_len} chars. Too long for context.]...\n\n" + m["content"][-5000:]
                
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

    def _get_auto_rag_context(self, user_text):
        context_parts = []
        try:
            from .sqlite_memory import SqliteMemoryDB
            mem_db = SqliteMemoryDB()
            # Extract basic keywords from prompt for searching (simplistic approach)
            import re
            # Filter out common stop words or very short words
            keywords = [w for w in re.split(r'\W+', user_text) if len(w) > 1][:5]
            if keywords:
                query = " OR ".join(keywords)
                # 1. Search Episodic Memory
                past_conv = mem_db.search_conversations(query, limit=2)
                if past_conv and not past_conv.startswith("Error") and not past_conv.startswith("No past"):
                    context_parts.append(f"--- Similar Past Conversations ---\n{past_conv}")
                
                # 2. Search Skills
                from qgis.core import QgsProject
                import os, json
                prj_home = QgsProject.instance().homePath()
                if prj_home:
                    index_file = os.path.join(prj_home, "agent_skills", "skills_index.json")
                    if os.path.exists(index_file):
                        with open(index_file, "r", encoding="utf-8") as f:
                            index_data = json.load(f)
                        matches = []
                        for s_name, s_info in index_data.items():
                            if any(k.lower() in s_name.lower() or k.lower() in s_info.get("description", "").lower() for k in keywords):
                                code_path = os.path.join(prj_home, "agent_skills", s_info["file"])
                                if os.path.exists(code_path):
                                    with open(code_path, "r", encoding="utf-8") as cf:
                                        matches.append(f"Skill: {s_name}\nCode:\n```python\n{cf.read()}\n```")
                        if matches:
                            context_parts.append(f"--- Relevant Procedural Skills ---\n" + "\n\n".join(matches[:2]))
        except Exception as e:
            self.logger.warning(f"Auto-RAG failed: {e}")
            
        if context_parts:
            return "[System Auto-RAG (Passive Memory Injection)]\n" + "\n\n".join(context_parts)
        return ""

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
        
        # Process Meltdown "Continue" Trigger
        continue_keywords = ["继续尝试", "继续", "再试一次", "再试", "keep trying", "try again", "continue"]
        if any(k in self.user_input.lower() for k in continue_keywords):
            lateral_prompt = "\n\n[System Auto-Trigger]: 之前的方法已经证明彻底失效（已熔断）。由于用户要求继续尝试，你现在【必须】彻底放弃之前的代码架构和使用的类库。请尝试使用完全不同的替代方案（例如：放弃 PyQGIS 接口，改用原生 GDAL/OGR 处理；或者换一个不同的算法处理逻辑）。"
            self.user_input += lateral_prompt
            
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
        
        # Self-repair: Fix hanging tool_calls from previously interrupted sessions
        # If the user kills the thread during tool execution, the assistant's tool_calls message
        # is saved to memory, but the corresponding 'tool' response is never appended.
        # This causes OpenAI to throw a 400 BadRequest on the next turn.
        if self.messages and self.messages[-1].get("role") == "assistant" and self.messages[-1].get("tool_calls"):
            self.logger.warning("Detected hanging tool_calls from an interrupted session. Injecting repair messages...")
            for tc in self.messages[-1]["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, 'id', '')
                if tc_id:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "Error: Tool execution was cancelled by the user in the previous session."
                    })
        
        # Process Auto-Reflection Trigger
        completion_keywords = ["完成", "结束", "好了", "done", "finish"]
        if any(k in self.user_input.lower() for k in completion_keywords):
            reflection_prompt = "\n\n[System Auto-Trigger]: The user indicates the current task might be completed. Please take a moment to reflect on any new constraints, project quirks, or user preferences you learned during this session. If there are new insights, you MUST use the `write_file` or `replace_file_content` tool to update MEMORY.md or USER.md before asking the user for their next task."
            self.user_input += reflection_prompt
            
        self.messages.append({"role": "user", "content": self.user_input})
        
        try:
            while True:
                if self.is_killed:
                    self.logger.info("Agent thread was killed by user.")
                    self.append_message_signal.emit("SYSTEM", "🛑 Operation stopped by user.")
                    break
                    
                self.append_message_signal.emit("SYSTEM", "Thinking...")
                
                # Inject dynamic QGIS context into the messages before sending
                # Inject dynamic QGIS context into the messages before sending
                # DYNAMIC SLIDING WINDOW: Keep System Prompt + Recent messages up to ~40000 chars to prevent context overflow
                messages_to_send = []
                system_msgs = [m for m in self.messages if m.get("role") == "system"]
                other_msgs = [m for m in self.messages if m.get("role") != "system"]
                
                messages_to_send.extend(system_msgs)
                
                # Dynamic accumulation from the end
                char_limit = 40000
                current_chars = 0
                dynamic_other_msgs = []
                
                for m in reversed(other_msgs):
                    m_len = len(str(m.get("content", "")))
                    if current_chars + m_len > char_limit and len(dynamic_other_msgs) > 0:
                        break
                    dynamic_other_msgs.insert(0, m)
                    current_chars += m_len
                    
                # Fix API Error 400: Truncation might leave orphaned "tool" messages at the beginning 
                # without their preceding "assistant" tool_calls message.
                while dynamic_other_msgs and dynamic_other_msgs[0].get("role") == "tool":
                    dynamic_other_msgs.pop(0)
                    
                messages_to_send.extend(dynamic_other_msgs)
                
                dynamic_context = self._get_qgis_context()
                if getattr(self, "ghost_context", None):
                    dynamic_context += "\n\n[System Auto-Injected Context based on @ Mentions]:\n" + self.ghost_context
                
                # Inject Auto-RAG
                auto_rag = self._get_auto_rag_context(self.user_input)
                if auto_rag:
                    dynamic_context += "\n\n" + auto_rag
                    
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
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError as e:
                        self.logger.error(f"JSON decode error for tool {name}: {e}")
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": f"JSON decode error in arguments: {e}. Please ensure you output valid JSON."
                        })
                        continue
                    
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

                    elif name in ["list_layers", "zoom_to_layer", "set_layer_visibility", "take_qgis_window_snapshot", "inspect_layer_fields", "get_selected_features", "select_features_by_expression", "clear_selection", "zoom_to_selected", "run_processing_algorithm", "create_geodatabase", "query_pyqgis_doc", "download_osm_data", "search_gee_python_api"]:
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
                        
                    elif name == "read_file":
                        file_path = args.get("file_path", "")
                        
                        import os
                        from qgis.core import QgsProject
                        # Smart path resolution for LLM
                        if file_path == "MEMORY.md" or file_path == "./MEMORY.md":
                            if QgsProject.instance().homePath():
                                file_path = os.path.join(QgsProject.instance().homePath(), "MEMORY.md")
                        elif file_path == "USER.md" or file_path == "./USER.md":
                            file_path = os.path.join(self.plugin_dir, "USER.md")
                        elif not os.path.isabs(file_path) and QgsProject.instance().homePath():
                            file_path = os.path.join(QgsProject.instance().homePath(), file_path)
                            
                        self.logger.info(f"Agent reading file: {file_path}")
                        try:
                            import os
                            if not os.path.exists(file_path):
                                result = f"Error: File not found at {file_path}"
                            else:
                                with open(file_path, "r", encoding="utf-8") as f:
                                    result = f.read()
                        except Exception as e:
                            result = f"Error reading file: {str(e)}"
                        
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })
                        
                    elif name == "write_file":
                        file_path = args.get("file_path", "")
                        content = args.get("content", "")
                        
                        import os
                        from qgis.core import QgsProject
                        # Smart path resolution for LLM
                        if file_path == "MEMORY.md" or file_path == "./MEMORY.md":
                            if QgsProject.instance().homePath():
                                file_path = os.path.join(QgsProject.instance().homePath(), "MEMORY.md")
                        elif file_path == "USER.md" or file_path == "./USER.md":
                            file_path = os.path.join(self.plugin_dir, "USER.md")
                        elif not os.path.isabs(file_path) and QgsProject.instance().homePath():
                            file_path = os.path.join(QgsProject.instance().homePath(), file_path)
                            
                        self.logger.info(f"Agent writing file: {file_path}")
                        try:
                            import os
                            os.makedirs(os.path.dirname(file_path), exist_ok=True)
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(content)
                            result = f"Successfully wrote to {file_path}"
                            if file_path.endswith(".md"):
                                self.append_message_signal.emit("AGENT", f"📝 **[Artifact Created: {os.path.basename(file_path)}]**\n\n{content}")
                        except Exception as e:
                            result = f"Error writing file: {str(e)}"
                            
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })
                        
                    elif name == "replace_file_content":
                        file_path = args.get("file_path", "")
                        
                        import os
                        from qgis.core import QgsProject
                        # Smart path resolution for LLM
                        if file_path == "MEMORY.md" or file_path == "./MEMORY.md":
                            if QgsProject.instance().homePath():
                                file_path = os.path.join(QgsProject.instance().homePath(), "MEMORY.md")
                        elif file_path == "USER.md" or file_path == "./USER.md":
                            file_path = os.path.join(self.plugin_dir, "USER.md")
                        elif not os.path.isabs(file_path) and QgsProject.instance().homePath():
                            file_path = os.path.join(QgsProject.instance().homePath(), file_path)
                            
                        target_content = args.get("target_content", "")
                        replacement_content = args.get("replacement_content", "")
                        self.logger.info(f"Agent replacing content in: {file_path}")
                        try:
                            import os
                            if not os.path.exists(file_path):
                                result = f"Error: File not found at {file_path}"
                            else:
                                with open(file_path, "r", encoding="utf-8") as f:
                                    file_data = f.read()
                                
                                if target_content not in file_data:
                                    result = "Error: target_content not found in file."
                                else:
                                    file_data = file_data.replace(target_content, replacement_content)
                                    with open(file_path, "w", encoding="utf-8") as f:
                                        f.write(file_data)
                                    result = f"Successfully replaced content in {file_path}"
                                    if file_path.endswith(".md"):
                                        self.append_message_signal.emit("AGENT", f"📝 **[Artifact Updated: {os.path.basename(file_path)}]**\n\n```diff\n- {target_content.strip()}\n+ {replacement_content.strip()}\n```")
                        except Exception as e:
                            result = f"Error replacing content: {str(e)}"
                            
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })

                    elif name == "save_skill":
                        skill_name = args.get("skill_name", "")
                        description = args.get("description", "")
                        python_code = args.get("python_code", "")
                        self.logger.info(f"Agent saving skill: {skill_name}")
                        try:
                            from qgis.core import QgsProject
                            import os, json
                            prj_home = QgsProject.instance().homePath()
                            if not prj_home:
                                result = "Error: QGIS Project is not saved. Cannot save skills without a project directory."
                            else:
                                skills_dir = os.path.join(prj_home, "agent_skills")
                                os.makedirs(skills_dir, exist_ok=True)
                                
                                skill_file = os.path.join(skills_dir, f"{skill_name}.py")
                                with open(skill_file, "w", encoding="utf-8") as f:
                                    f.write(python_code)
                                    
                                index_file = os.path.join(skills_dir, "skills_index.json")
                                index_data = {}
                                if os.path.exists(index_file):
                                    with open(index_file, "r", encoding="utf-8") as f:
                                        index_data = json.load(f)
                                        
                                index_data[skill_name] = {"description": description, "file": f"{skill_name}.py"}
                                with open(index_file, "w", encoding="utf-8") as f:
                                    json.dump(index_data, f, ensure_ascii=False, indent=2)
                                    
                                result = f"Successfully saved skill '{skill_name}' to {skills_dir}"
                        except Exception as e:
                            result = f"Error saving skill: {str(e)}"
                            
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })
                        
                    elif name == "search_skills":
                        query = args.get("query", "").lower()
                        self.logger.info(f"Agent searching skills for: {query}")
                        try:
                            from qgis.core import QgsProject
                            import os, json
                            prj_home = QgsProject.instance().homePath()
                            if not prj_home:
                                result = "Error: QGIS Project is not saved."
                            else:
                                index_file = os.path.join(prj_home, "agent_skills", "skills_index.json")
                                if not os.path.exists(index_file):
                                    result = "No skills library found in this project."
                                else:
                                    with open(index_file, "r", encoding="utf-8") as f:
                                        index_data = json.load(f)
                                        
                                    matches = []
                                    for s_name, s_info in index_data.items():
                                        if query in s_name.lower() or query in s_info.get("description", "").lower():
                                            code_path = os.path.join(prj_home, "agent_skills", s_info["file"])
                                            if os.path.exists(code_path):
                                                with open(code_path, "r", encoding="utf-8") as cf:
                                                    code = cf.read()
                                                matches.append(f"--- Skill: {s_name} ---\nDescription: {s_info['description']}\nCode:\n```python\n{code}\n```")
                                                
                                    if matches:
                                        result = "Found the following skills:\n\n" + "\n\n".join(matches)
                                    else:
                                        result = f"No skills found matching '{query}'."
                        except Exception as e:
                            result = f"Error searching skills: {str(e)}"
                            
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })
                        
                    elif name == "search_past_conversations":
                        query = args.get("query", "")
                        self.logger.info(f"Agent searching episodic memory for: {query}")
                        try:
                            from .sqlite_memory import SqliteMemoryDB
                            db = SqliteMemoryDB()
                            result = db.search_conversations(query)
                        except Exception as e:
                            result = f"Error searching memory: {str(e)}"
                            
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": result
                        })

                    elif name == "submit_plan_for_approval":
                        plan_markdown = args.get("plan_markdown", "")
                        if not plan_markdown:
                            self.logger.warning("Agent attempted to submit plan without providing plan_markdown")
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": name,
                                "content": "Error: You MUST provide your full markdown checklist in the 'plan_markdown' argument."
                            })
                            continue
                            
                        from qgis.core import QgsProject
                        import os
                        home = QgsProject.instance().homePath()
                        if home:
                            task_path = os.path.join(home, "task.md")
                            try:
                                with open(task_path, "w", encoding="utf-8") as f:
                                    f.write(plan_markdown)
                                self.logger.info(f"Automatically wrote plan_markdown to {task_path}")
                                self.append_message_signal.emit("SYSTEM", "📝 **[Artifact Created: task.md]**\n\n(系统已根据您的计划自动生成任务文件)")
                            except Exception as e:
                                self.logger.error(f"Failed to write task.md: {e}")
                            
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
                        
                        import re
                        if re.search(r'\b(os\.remove|os\.unlink|os\.rmdir|shutil\.rmtree)\b', code):
                            is_destructive = True
                            
                        self.logger.debug(f"Agent attempting to execute code (Destructive: {is_destructive}):\n{code}")
                        
                        if is_destructive:
                            self.logger.warning("Agent requested destructive auth.")
                            self.destructive_auth_event.clear()
                            self.request_destructive_auth_signal.emit(code)
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
                        if "[EXECUTION_FAILED_TRACEBACK]" in output:
                            self._error_retries = getattr(self, "_error_retries", 0) + 1
                            if self._error_retries >= 4:
                                meltdown_msg = "🛑 **Agent 遇到死胡同已暂停**\n我已经连续 3 次局部修复以及 1 次全局反思均告失败。为了保护运行环境，我已主动熔断。\n你可以这样帮我：\n1. 如果你有相关的 QGIS 3.44 文档代码或 API 变化信息，请直接发给我。\n2. 授权我使用搜索工具（如 search_web）去网上查一下这个报错。\n3. 或者回复 **“继续尝试”**，我将彻底放弃当前思路，换一种全新的逻辑或算法。"
                                self.append_message_signal.emit("SYSTEM", meltdown_msg)
                                self.messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": name,
                                    "content": output + "\n\n[SYSTEM] Max error retries reached. Agent execution halted. Waiting for human intervention."
                                })
                                self._error_retries = 0
                                break_outer_loop = True
                                break
                            elif self._error_retries == 3:
                                task_content = ""
                                try:
                                    import os
                                    from qgis.core import QgsProject
                                    proj_path = QgsProject.instance().fileName()
                                    proj_dir = os.path.dirname(proj_path) if proj_path else os.path.expanduser("~")
                                    task_file = os.path.join(proj_dir, "task.md")
                                    if os.path.exists(task_file):
                                        with open(task_file, "r", encoding="utf-8") as f:
                                            task_content = f.read()
                                except Exception:
                                    pass
                                critic_analysis = self._run_critic_agent(output, code, task_content)
                                output = f"[SYSTEM CRITIC]: 局部修复已连续失效！启动全局反思：\n\n{critic_analysis}\n\n[SYSTEM DIRECTIVE] 请仔细阅读以上 Critic 的建议！如果错误是由上一步的脏数据引起的，请使用 `replace_file_content` 修改 `task.md` 倒退进度，并重新执行之前的步骤。"
                            else:
                                debugger_analysis = self._run_debugger_agent(output, code)
                                output = f"[SYSTEM Debugger Analysis]:\n{debugger_analysis}\n\n[SYSTEM] Execution failed. You have {3 - self._error_retries} local retries left before Critic intervention. Please apply the Debugger's suggested fix."
                        else:
                            self._error_retries = 0
                        
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": output
                        })
                    else:
                        # Fallback to atomic tools
                        from ..tools.tools import execute_atomic_tool
                        self.logger.debug(f"Delegating tool execution to atomic tools: {name}")
                        try:
                            from qgis.utils import iface
                            output = execute_atomic_tool(iface, name, args)
                        except Exception as e:
                            output = f"Error executing {name}: {str(e)}"
                            
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

    def _run_debugger_agent(self, traceback_str, code_str):
        self.append_message_signal.emit("SYSTEM", "🔍 正在调用后台 Debugger Agent 分析报错原因...")
        prompt = f"""You are an expert QGIS Python Debugger. 
The main agent wrote the following script which failed with an error.
Your task is to analyze the traceback and provide a very concise explanation of what went wrong, and the corrected code.

[Faulty Code]:
{code_str}

[Traceback]:
{traceback_str}

Respond in the following format:
**Error Analysis**: (brief explanation)
**Suggested Fix**: (how to fix it)
**Corrected Code**: 
```python
(the full corrected code)
```
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.2
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Debugger Agent failed to run: {str(e)}\nRaw Traceback:\n{traceback_str}"

    def _run_critic_agent(self, traceback_str, code_str, task_content):
        self.append_message_signal.emit("SYSTEM", "🧠 局部修复失效，正在调用 Critic Agent 进行全局反思...")
        prompt = f"""You are a Senior GIS Architect and Critic.
The main agent has been stuck in an error loop attempting to execute a PyQGIS script. 
The local debugger failed to fix it 2 times. Your job is to look at the bigger picture.

[Task Progress (task.md)]:
{task_content}

[Current Failing Code]:
{code_str}

[Traceback]:
{traceback_str}

Analyze the situation. Is the error caused by a fundamental flaw in the input data (e.g., wrong geometry type like MultiPoint instead of Point, wrong CRS, missing fields) that was generated by a PREVIOUS step? 
If so, instruct the main agent to STOP fixing the current code, and instead ROLLBACK to the previous step to regenerate the data correctly (e.g., by adding native:centroids or reprojecting).

Respond concisely with:
**Root Cause Analysis**: (Why is this failing repeatedly?)
**Rollback & Fix Strategy**: (What exact steps/tools should the agent use to regenerate the previous data correctly?)
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "system", "content": prompt}],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Critic Agent failed to run: {str(e)}\nRaw Traceback:\n{traceback_str}"
