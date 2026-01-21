import os
import sys
import shlex
import json
import asyncio
import subprocess
import warnings
import platform
from datetime import datetime
from dotenv import load_dotenv

# OS判定
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# SpeechRecognition のインポート試行
try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

# Whisper のインポート試行
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

warnings.filterwarnings("ignore")

# MCP のインポート試行
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# google-genai SDK のインポート
try:
    from google import genai
    from google.genai import types
    GENAI_NEW_SDK = True
except ImportError:
    # フォールバック: 旧SDK
    import google.generativeai as genai_legacy
    GENAI_NEW_SDK = False


def call_speak_py(text):
    """Calls the speak.py script to read the given text aloud."""
    speak_script_path = os.path.join(os.path.dirname(__file__), "speak.py")
    
    if not os.path.exists(speak_script_path):
        print(f"Error: 'speak.py' not found at {speak_script_path}", file=sys.stderr)
        return

    try:
        subprocess.Popen([sys.executable, speak_script_path, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"Error calling speak.py: {e}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred when trying to run speak.py: {e}", file=sys.stderr)


# 会話ログ管理クラス
class ConversationLogger:
    """セッションごとの会話ログを管理"""
    
    def __init__(self):
        self.log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        
        # セッション開始時刻でファイル名を生成
        session_time = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = os.path.join(self.log_dir, f'chat_{session_time}.log')
        
        # ログファイルのヘッダーを書き込み
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== Chat Session Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
        
        print(f"Log file: {self.log_file}")
    
    def log(self, speaker: str, content: str):
        """会話を記録"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {speaker}: {content}\n"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def close(self):
        """セッション終了を記録"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n=== Chat Session Ended: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")


def get_stt_engine_config():
    """STT エンジン設定を取得"""
    stt_engine = os.getenv("STT_ENGINE", "google").lower()
    
    if stt_engine == "whisper":
        if WHISPER_AVAILABLE:
            return "whisper"
        else:
            print("Warning: Whisper not available, falling back to Google.", file=sys.stderr)
            return "google"
    else:
        if SR_AVAILABLE:
            return "google"
        else:
            print("Warning: SpeechRecognition not available.", file=sys.stderr)
            return None


def listen_with_google(recognizer, mic):
    """Google Web Speech API で音声認識"""
    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
    return recognizer.recognize_google(audio, language='ja-JP')


def listen_with_whisper(whisper_model, recognizer, mic):
    """Whisper で音声認識"""
    import tempfile
    
    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
    
    # 一時ファイルに保存して Whisper で処理
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name
        wav_data = audio.get_wav_data()
        f.write(wav_data)
    
    try:
        result = whisper_model.transcribe(temp_path, language="ja")
        return result["text"]
    finally:
        os.unlink(temp_path)


async def main_async():
    # 環境変数の読み込み
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    load_dotenv(dotenv_path=dotenv_path)

    # API キー確認
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not found.", file=sys.stderr)
        print("Please create a .env file with: GEMINI_API_KEY='your_api_key_here'", file=sys.stderr)
        sys.exit(1)

    # MCP サーバ接続
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
            print("Note: 'mcp' package not installed. Install with 'pip install mcp' for MCP features.")
        elif not mcp_command:
            print("Note: MCP_SERVER_COMMAND not set. Running without MCP capabilities.")
        
        await run_chat_session(api_key, None)


async def run_chat_session(api_key, mcp_session=None):
    # モデル設定の読み込み
    model_normal = os.getenv("GEMINI_MODEL_NORMAL", "gemini-2.0-flash-lite")
    model_high = os.getenv("GEMINI_MODEL_HIGH", "gemini-2.0-flash")
    use_google_search = os.getenv("USE_GOOGLE_SEARCH", "true").lower() == "true"
    
    print(f"Models: Normal={model_normal}, High={model_high}")
    print(f"Google Search: {'Enabled' if use_google_search else 'Disabled'}")
    print(f"SDK: {'google-genai (new)' if GENAI_NEW_SDK else 'google-generativeai (legacy)'}")
    
    # MCP ツールの取得
    mcp_tools = []
    if mcp_session:
        try:
            result = await mcp_session.list_tools()
            for tool in result.tools:
                mcp_tools.append({
                    'name': tool.name,
                    'description': tool.description,
                    'parameters': tool.inputSchema
                })
            print(f"Loaded {len(mcp_tools)} tools from MCP server.")
        except Exception as e:
            print(f"Error loading tools from MCP server: {e}", file=sys.stderr)

    # システムプロンプト
    system_instruction = """あなたは音声対話アシスタントです。
ユーザーの入力に対して、以下のJSON形式で返答してください。
{
    "display_text": "画面に表示するテキスト（漢字を含んで自然な日本語）",
    "speech_text": "音声合成用のテキスト（すべてひらがな）"
}

重要：
- 最新の情報が必要な質問には、Google検索を使用して情報を取得してください。
- 検索結果を参照した場合は、その旨を回答に含めてください。
- 必ず上記のJSON形式のみを出力してください。"""

    print("\nGemini Chat CLI. Type 'exit' or 'quit' to end.")
    print("-" * 50)

    # 音声認識の初期化
    stt_engine = get_stt_engine_config()
    recognizer = None
    mic = None
    whisper_model = None
    
    if stt_engine == "google" and SR_AVAILABLE:
        try:
            recognizer = sr.Recognizer()
            mic = sr.Microphone()
            print(f"Voice input: Google Web Speech API")
        except Exception as e:
            print(f"Warning: Voice input initialization failed: {e}", file=sys.stderr)
            stt_engine = None
    elif stt_engine == "whisper" and WHISPER_AVAILABLE:
        try:
            recognizer = sr.Recognizer()
            mic = sr.Microphone()
            whisper_model = whisper.load_model("base")
            print(f"Voice input: Whisper (base model)")
        except Exception as e:
            print(f"Warning: Whisper initialization failed: {e}", file=sys.stderr)
            stt_engine = None

    # 会話ログの初期化
    logger = ConversationLogger()
    
    # SDK に応じたクライアント初期化
    if GENAI_NEW_SDK:
        # 新SDK (google-genai)
        client = genai.Client(api_key=api_key)
        chat_history = []
        
        while True:
            try:
                prompt_text = "You (Enter for Voice): " if stt_engine else "You: "
                prompt = await asyncio.to_thread(input, prompt_text)
                
                # 音声入力
                if not prompt and stt_engine:
                    print("Listening... (Speak now)")
                    try:
                        if stt_engine == "google":
                            prompt = await asyncio.to_thread(listen_with_google, recognizer, mic)
                        elif stt_engine == "whisper":
                            prompt = await asyncio.to_thread(listen_with_whisper, whisper_model, recognizer, mic)
                        print(f"You said: {prompt}")
                    except Exception as e:
                        print(f"Voice recognition failed: {e}")
                        continue

                if prompt.lower() in ["exit", "quit"]:
                    print("\nGoodbye!")
                    logger.close()
                    break
                if not prompt:
                    continue

                # ツール設定
                tools = []
                if use_google_search:
                    tools.append(types.Tool(google_search=types.GoogleSearch()))
                
                # MCP ツールは別途処理が必要（新SDKでのカスタムツール対応）
                
                # コンテンツ設定
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools if tools else None,
                    response_mime_type="application/json"
                )
                
                # 履歴にユーザーメッセージを追加
                chat_history.append(types.Content(
                    role="user",
                    parts=[types.Part(text=prompt)]
                ))
                
                # ユーザー入力をログに記録
                logger.log("User", prompt)
                
                # メッセージ送信 (リトライロジック付き)
                max_retries = 3
                retry_delay = 5
                response = None
                
                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model=model_normal,
                            contents=chat_history,
                            config=config
                        )
                        break  # 成功したらループを抜ける
                    except Exception as e:
                        error_str = str(e)
                        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                            if attempt < max_retries - 1:
                                print(f"[Rate limit hit, retrying in {retry_delay}s... ({attempt + 1}/{max_retries})]")
                                print(f"[Error details: {error_str}]", file=sys.stderr)
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # 指数バックオフ
                            else:
                                print(f"[Rate limit exceeded after {max_retries} retries]", file=sys.stderr)
                                import traceback
                                traceback.print_exc()
                                raise
                        else:
                            print(f"[API Error: {error_str}]", file=sys.stderr)
                            import traceback
                            traceback.print_exc()
                            raise
                
                if response is None:
                    continue
                
                # 履歴にアシスタントの応答を追加
                if response.text:
                    chat_history.append(types.Content(
                        role="model",
                        parts=[types.Part(text=response.text)]
                    ))
                    
                    try:
                        response_data = json.loads(response.text)
                        display_text = response_data.get("display_text", response.text)
                        speech_text = response_data.get("speech_text", response.text)
                        print(f"Gemini: {display_text}\n")
                        call_speak_py(speech_text)
                        # アシスタント応答をログに記録
                        logger.log("Assistant", display_text)
                    except json.JSONDecodeError:
                        print(f"Gemini: {response.text}\n")
                        call_speak_py(response.text)
                        # アシスタント応答をログに記録
                        logger.log("Assistant", response.text)

            except KeyboardInterrupt:
                print("\n\nCaught KeyboardInterrupt, exiting.")
                logger.close()
                break
            except Exception as e:
                print(f"\nAn error occurred: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                continue
    else:
        # 旧SDK (google-generativeai) - Grounding非対応
        genai_legacy.configure(api_key=api_key)
        
        model = genai_legacy.GenerativeModel(
            model_normal,
            tools=mcp_tools if mcp_tools else None,
            system_instruction=system_instruction,
            generation_config={"response_mime_type": "application/json"}
        )
        chat = model.start_chat(history=[])

        while True:
            try:
                prompt_text = "You (Enter for Voice): " if stt_engine else "You: "
                prompt = await asyncio.to_thread(input, prompt_text)
                
                # 音声入力
                if not prompt and stt_engine:
                    print("Listening... (Speak now)")
                    try:
                        if stt_engine == "google":
                            prompt = await asyncio.to_thread(listen_with_google, recognizer, mic)
                        elif stt_engine == "whisper":
                            prompt = await asyncio.to_thread(listen_with_whisper, whisper_model, recognizer, mic)
                        print(f"You said: {prompt}")
                    except Exception as e:
                        print(f"Voice recognition failed: {e}")
                        continue

                if prompt.lower() in ["exit", "quit"]:
                    print("\nGoodbye!")
                    logger.close()
                    break
                if not prompt:
                    continue

                # ユーザー入力をログに記録
                logger.log("User", prompt)
                
                # メッセージ送信
                response = await chat.send_message_async(prompt)
                
                # Function call ループ
                while response.parts and response.parts[0].function_call:
                    fc = response.parts[0].function_call
                    func_name = fc.name
                    func_args = dict(fc.args)
                    
                    print(f"[Calling tool: {func_name}]")
                    
                    if mcp_session:
                        try:
                            mcp_result = await mcp_session.call_tool(func_name, arguments=func_args)
                            
                            tool_output = ""
                            if not mcp_result.isError:
                                for content in mcp_result.content:
                                    if content.type == "text":
                                        tool_output += content.text
                            else:
                                tool_output = "Error executing tool."
                                
                            response = await chat.send_message_async(
                                genai_legacy.protos.Content(
                                    parts=[genai_legacy.protos.Part(
                                        function_response=genai_legacy.protos.FunctionResponse(
                                            name=func_name,
                                            response={'result': tool_output}
                                        )
                                    )]
                                )
                            )
                        except Exception as e:
                            print(f"Error executing tool {func_name}: {e}", file=sys.stderr)
                            response = await chat.send_message_async(
                                genai_legacy.protos.Content(
                                    parts=[genai_legacy.protos.Part(
                                        function_response=genai_legacy.protos.FunctionResponse(
                                            name=func_name,
                                            response={'error': str(e)}
                                        )
                                    )]
                                )
                            )
                    else:
                        print("Error: MCP session not active but model requested tool.", file=sys.stderr)
                        break

                # 応答の表示と音声出力
                if response.text:
                    try:
                        response_data = json.loads(response.text)
                        display_text = response_data.get("display_text", response.text)
                        speech_text = response_data.get("speech_text", response.text)
                        print(f"Gemini: {display_text}\n")
                        call_speak_py(speech_text)
                        # アシスタント応答をログに記録
                        logger.log("Assistant", display_text)
                    except json.JSONDecodeError:
                        print(f"Gemini: {response.text}\n")
                        call_speak_py(response.text)
                        # アシスタント応答をログに記録
                        logger.log("Assistant", response.text)

            except KeyboardInterrupt:
                print("\n\nCaught KeyboardInterrupt, exiting.")
                logger.close()
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
