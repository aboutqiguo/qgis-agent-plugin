import sqlite3
import os
import json
from qgis.core import QgsProject

class SqliteMemoryDB:
    def __init__(self):
        self.db_path = ""
        self.conn = None
        
    def _get_db_path(self):
        home = QgsProject.instance().homePath()
        if not home:
            return None
        return os.path.join(home, "qgis_agent_memory.db")
        
    def _init_db(self):
        path = self._get_db_path()
        if not path:
            return False
            
        if self.db_path != path or not self.conn:
            if self.conn:
                self.conn.close()
            self.db_path = path
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = self.conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    content TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    role, content, content='messages', content_rowid='id'
                )
            ''')
            
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                  INSERT INTO messages_fts(rowid, role, content) VALUES (new.id, new.role, new.content);
                END;
            ''')
            self.conn.commit()
        return True
        
    def save_messages(self, messages_list):
        if not self._init_db():
            return
            
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM messages_fts")
        
        for msg in messages_list:
            role = msg.get("role", "")
            # Serialize the entire message dictionary to preserve tool_calls and tool_call_id
            json_str = json.dumps(msg, ensure_ascii=False)
            cursor.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, json_str))
            
        self.conn.commit()
        
    def load_messages(self):
        if not self._init_db():
            return []
            
        cursor = self.conn.cursor()
        cursor.execute("SELECT role, content FROM messages ORDER BY id ASC")
        rows = cursor.fetchall()
        
        messages = []
        for role, content in rows:
            try:
                # Try to parse the content as a full JSON message dict (new format)
                if content.strip().startswith("{") and '"role"' in content:
                    msg_dict = json.loads(content)
                    if "role" not in msg_dict:
                        msg_dict["role"] = role
                    messages.append(msg_dict)
                else:
                    # Fallback for old database format
                    messages.append({"role": role, "content": content})
            except:
                messages.append({"role": role, "content": content})
                
        # --- Sanitize corrupted history from old plugin versions ---
        sanitized_messages = []
        for msg in messages:
            r = msg.get("role")
            
            # If it's a tool message but missing tool_call_id, flatten it to a user message
            if r == "tool" and "tool_call_id" not in msg:
                sanitized_messages.append({
                    "role": "user",
                    "content": f"[Previous Tool Result]:\n{msg.get('content', '')}"
                })
                continue
                
            # If it's an assistant message missing content, ensure it's not None
            if r == "assistant":
                if "content" not in msg or msg["content"] is None:
                    msg["content"] = ""
                    
            sanitized_messages.append(msg)
            
        return sanitized_messages
        
    def search_conversations(self, query, limit=5):
        if not self._init_db():
            return "Error: QGIS Project is not saved."
            
        cursor = self.conn.cursor()
        # Sanitize query for FTS MATCH
        sanitized_query = query.replace('"', '""')
        try:
            cursor.execute('''
                SELECT role, content FROM messages_fts 
                WHERE messages_fts MATCH ? 
                ORDER BY rank LIMIT ?
            ''', (f'"{sanitized_query}"', limit))
            results = cursor.fetchall()
            if not results:
                return "No past conversations found matching the query."
                
            out = []
            for role, content in results:
                # Truncate content to avoid blowing up context
                trunc = content[:1000] + "..." if len(content) > 1000 else content
                out.append(f"[{role}]: {trunc}")
            return "\n\n".join(out)
        except Exception as e:
            return f"Error searching memory: {str(e)}"
