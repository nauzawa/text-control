import pyttsx3
import sys
import platform

# OS判定
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


def list_voices(engine):
    """Lists all available TTS voices."""
    print("Available voices:")
    voices = engine.getProperty('voices')
    if not voices:
        print("No voices found. Please make sure you have a TTS engine installed.")
        return
    for i, voice in enumerate(voices):
        print(f"  Voice {i}:")
        print(f"    Name: {voice.name}")
        print(f"    ID: {voice.id}")
        print(f"    Languages: {voice.languages}")
    print("-" * 20)


def speak(text, engine):
    """
    Finds a Japanese voice, sets it, and then says the given text.
    """
    voices = engine.getProperty('voices')
    jp_voice_id = None

    # Search for a Japanese voice
    for voice in voices:
        # Check for common Japanese voice names/identifiers
        if 'japanese' in voice.name.lower() or 'haruka' in voice.name.lower():
            jp_voice_id = voice.id
            break

    if jp_voice_id:
        print(f"Found Japanese voice. Using: {jp_voice_id}")
        engine.setProperty('voice', jp_voice_id)
    else:
        print("Japanese voice not found. Using the default voice.")
        if IS_WINDOWS:
            print("For Japanese speech, please install a Japanese language pack in your OS.")
        elif IS_LINUX:
            print("For Japanese speech on Linux, install: sudo apt-get install espeak-ng-espeak")
        current_voice = engine.getProperty('voice')
        print(f"Default voice ID: {current_voice}")

    engine.say(text)
    engine.runAndWait()


def init_engine():
    """Initialize the TTS engine based on the OS."""
    try:
        if IS_LINUX:
            # Linux では espeak ドライバを明示的に指定
            try:
                engine = pyttsx3.init(driverName='espeak')
            except Exception:
                # フォールバック: デフォルトドライバ
                engine = pyttsx3.init()
        else:
            # Windows (SAPI5) やその他
            engine = pyttsx3.init()
        return engine
    except Exception as e:
        print(f"Failed to initialize pyttsx3. Error: {e}")
        print("Please ensure you have a text-to-speech engine installed.")
        if IS_WINDOWS:
            print("Windows: SAPI5 should be available by default.")
        elif IS_LINUX:
            print("Linux: Install espeak with: sudo apt-get install espeak espeak-ng")
        return None


if __name__ == "__main__":
    engine = init_engine()
    if engine is None:
        sys.exit(1)

    if len(sys.argv) == 2 and sys.argv[1] == '--list-voices':
        list_voices(engine)
        sys.exit()

    if len(sys.argv) > 1:
        text_to_speak = " ".join(sys.argv[1:])
        speak(text_to_speak, engine)
    else:
        print("Usage: python speak.py <text_to_speak>")
        print("   or: python speak.py --list-voices")
        print("Example: python speak.py 'こんにちは'")
