import os
import sys
import shlex
import json
import asyncio
import subprocess
import warnings
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import content_types

# Try to import SpeechRecognition
try:
    import speech_recognition as sr
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

warnings.filterwarnings("ignore")

# Try to import MCP
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

def call_speak_py(text):
    """Calls the speak.py script to read the given text aloud."""
    speak_script_path = os.path.join(os.path.dirname(__file__), "speak.py")
    
    # Check if speak.py exists
    if not os.path.exists(speak_script_path):
        print(f"Error: 'speak.py' not found at {speak_script_path}", file=sys.stderr)
        return

    try:
        # It's good practice to use sys.executable to ensure we use the same python interpreter
        subprocess.run([sys.executable, speak_script_path, text], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Error calling speak.py: {e}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred when trying to run speak.py: {e}", file=sys.stderr)

async def main_async():
    # --- Load environment variables ---
    # Look for .env in the same directory as the script
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=dotenv_path)

    # --- Configuration ---
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not found.", file=sys.stderr)
        print("Please create a .env file in the script directory with the following content:", file=sys.stderr)
        print("GEMINI_API_KEY='your_api_key_here'", file=sys.stderr)
        sys.exit(1)

    # Check for MCP configuration
    mcp_command = os.getenv("MCP_SERVER_COMMAND")
    mcp_args_str = os.getenv("MCP_SERVER_ARGS", "")
    mcp_args = shlex.split(mcp_args_str) if mcp_args_str else []
    
    if MCP_AVAILABLE and mcp_command:
        print(f"Connecting to MCP Server: {mcp_command} {' '.join(mcp_args)}...")
        try:
            server_params = StdioServerParameters(command=mcp_command, args=mcp_args, env=None)
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await run_chat_session(api_key, session)
        except Exception as e:
            print(f"Failed to connect to MCP server: {e}", file=sys.stderr)
            print("Falling back to standard chat.")
            await run_chat_session(api_key, None)
    else:
        if not MCP_AVAILABLE:
            print("Note: 'mcp' package not installed. Install with 'pip install mcp' to use MCP features.")
        elif not mcp_command:
            print("Note: MCP_SERVER_COMMAND not set in .env. Running without MCP capabilities.")
        
        await run_chat_session(api_key, None)

async def run_chat_session(api_key, mcp_session=None):
    genai.configure(api_key=api_key)
    
    tools = []
    if mcp_session:
        try:
            # Fetch tools from MCP server
            result = await mcp_session.list_tools()
            for tool in result.tools:
                tools.append({
                    'name': tool.name,
                    'description': tool.description,
                    'parameters': tool.inputSchema
                })
            print(f"Loaded {len(tools)} tools from MCP server.")
        except Exception as e:
            print(f"Error loading tools from MCP server: {e}", file=sys.stderr)

    # System instruction to request JSON output with display text and speech text
    system_instruction = """あなたは音声対話アシスタントです。
ユーザーの入力に対して、以下のJSON形式で返答してください。
{
    "display_text": "画面に表示するテキスト（漢字を含んで自然な日本語）",
    "speech_text": "音声合成用のテキスト（すべてひらがな）"
}"""

    # Initialize model with tools
    model = genai.GenerativeModel('gemini-2.5-flash-lite', tools=tools if tools else None, system_instruction=system_instruction, generation_config={"response_mime_type": "application/json"})
    chat = model.start_chat(history=[])

    print("\nGemini Chat CLI. Type 'exit' or 'quit' to end.")
    print("-" * 50)

    # Initialize recognizer if available
    recognizer = None
    mic = None
    if VOICE_AVAILABLE:
        try:
            recognizer = sr.Recognizer()
            mic = sr.Microphone()
        except Exception as e:
            print(f"Warning: Voice input initialization failed: {e}", file=sys.stderr)
            VOICE_AVAILABLE = False

    while True:
        try:
            # Use asyncio.to_thread for non-blocking input
            prompt_text = "You (Enter for Voice): " if VOICE_AVAILABLE else "You: "
            prompt = await asyncio.to_thread(input, prompt_text)
            
            # Handle voice input if prompt is empty and voice is available
            if not prompt and VOICE_AVAILABLE:
                print("Listening... (Speak now)")
                try:
                    def listen_and_recognize():
                        with mic as source:
                            recognizer.adjust_for_ambient_noise(source)
                            audio = recognizer.listen(source)
                        return recognizer.recognize_google(audio, language='ja-JP')
                    
                    prompt = await asyncio.to_thread(listen_and_recognize)
                    print(f"You said: {prompt}")
                except Exception as e:
                    print(f"Voice recognition failed: {e}")
                    continue

            if prompt.lower() in ["exit", "quit"]:
                print("\nGoodbye!")
                break
            if not prompt:
                continue

            # Send message asynchronously
            response = await chat.send_message_async(prompt)
            
            # Handle function calls loop
            while response.parts and response.parts[0].function_call:
                fc = response.parts[0].function_call
                func_name = fc.name
                func_args = dict(fc.args)
                
                print(f"[Gemini requests tool: {func_name}]")
                
                if mcp_session:
                    try:
                        # Call MCP tool
                        mcp_result = await mcp_session.call_tool(func_name, arguments=func_args)
                        
                        # Extract text content from result
                        tool_output = ""
                        if not mcp_result.isError:
                            for content in mcp_result.content:
                                if content.type == "text":
                                    tool_output += content.text
                        else:
                            tool_output = "Error executing tool."
                            
                        # Send result back to Gemini
                        response = await chat.send_message_async(
                            genai.protos.Content(
                                parts=[genai.protos.Part(
                                    function_response=genai.protos.FunctionResponse(
                                        name=func_name,
                                        response={'result': tool_output}
                                    )
                                )]
                            )
                        )
                    except Exception as e:
                        print(f"Error executing tool {func_name}: {e}", file=sys.stderr)
                        # Send error back
                        response = await chat.send_message_async(
                            genai.protos.Content(
                                parts=[genai.protos.Part(
                                    function_response=genai.protos.FunctionResponse(
                                        name=func_name,
                                        response={'error': str(e)}
                                    )
                                )]
                            )
                        )
                else:
                    print("Error: MCP session not active but model requested tool.", file=sys.stderr)
                    break

            # Print and speak response
            if response.text:
                try:
                    response_data = json.loads(response.text)
                    display_text = response_data.get("display_text", response.text)
                    speech_text = response_data.get("speech_text", response.text)
                    print(f"Gemini: {display_text}\n")
                    call_speak_py(speech_text)
                except json.JSONDecodeError:
                    print(f"Gemini: {response.text}\n")
                    call_speak_py(response.text)

        except KeyboardInterrupt:
            print("\n\nCaught KeyboardInterrupt, exiting.")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}", file=sys.stderr)
            continue

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
