from harness import AgentHarness

def main():
    print("==================================================")
    print("Welcome to the PyQGIS 4.0 AI Agent (Harness Edition)!")
    print("==================================================")
    print("Type 'exit' or 'quit' to stop.")
    
    harness = AgentHarness()
    
    while True:
        try:
            user_input = input("\n[USER (Type your GIS task)]: ")
            if user_input.lower() in ['exit', 'quit']:
                break
                
            if not user_input.strip():
                continue
                
            response = harness.chat(user_input)
            if response:
                print(f"\n[AGENT]: {response}")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
