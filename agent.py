import os
import glob
from llm_client import generate_pyqgis_code
from qgis_executor import execute_pyqgis_code

DOCS_DIR = 'pyqgis_4.0_docs'

def retrieve_context(user_prompt: str) -> str:
    """
    Naively search downloaded markdown docs for keywords from the prompt.
    """
    context = ""
    keywords = [word for word in user_prompt.replace(',',' ').replace('.',' ').split() if len(word) > 3]
    
    if not os.path.exists(DOCS_DIR):
        return ""
        
    md_files = glob.glob(os.path.join(DOCS_DIR, '*.md'))
    
    # Very basic retrieval: Match prompt keywords against filename
    matched_files = []
    for f in md_files:
        filename = os.path.basename(f).lower()
        if any(k.lower() in filename for k in keywords):
            matched_files.append(f)
            
    # Load up to 3 matched files as context
    for f in matched_files[:3]:
        try:
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read()
                # Trim context to avoid exceeding token limits
                if len(content) > 3000:
                    content = content[:3000] + "...(truncated)"
                context += f"\n--- Documentation from {os.path.basename(f)} ---\n{content}\n"
        except Exception:
            pass
            
    return context

def run_agent_loop():
    print("========================================")
    print("Welcome to the PyQGIS 4.0 AI Agent!")
    print("========================================")
    print("Type 'exit' or 'quit' to stop.")
    
    while True:
        try:
            user_prompt = input("\n[USER (Type your GIS task)]: ")
            if user_prompt.lower() in ['exit', 'quit']:
                break
            
            if not user_prompt.strip():
                continue
                
            print("\n[AGENT]: Searching local PyQGIS 4.0 documentation for context...")
            context = retrieve_context(user_prompt)
            if context:
                print(f"[AGENT]: Found {context.count('--- Documentation from')} relevant document(s).")
            else:
                print("[AGENT]: No specific local documentation matched. Relying on baseline model knowledge.")
            
            print("[AGENT]: Generating PyQGIS code via DeepSeek API...")
            try:
                code = generate_pyqgis_code(user_prompt, context)
                print("\n--- GENERATED CODE ---")
                print(code)
                print("----------------------\n")
            except Exception as e:
                print(f"[ERROR]: API Request failed: {e}")
                continue
                
            execute_choice = input("[AGENT]: Do you want to execute this code in QGIS sandbox? (y/n): ")
            if execute_choice.lower() == 'y':
                print("[AGENT]: Executing...")
                output = execute_pyqgis_code(code)
                print("\n=== EXECUTION RESULT ===")
                print(output)
                print("========================")
            else:
                print("[AGENT]: Execution skipped.")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Unexpected error: {e}")

if __name__ == '__main__':
    # Add a check for API KEY before starting
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("Error: DEEPSEEK_API_KEY is not set in the environment.")
    else:
        run_agent_loop()
