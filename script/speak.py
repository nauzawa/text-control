
import pyttsx3
import sys

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
        print("For Japanese speech, please install a Japanese language pack in your OS.")
        current_voice = engine.getProperty('voice')
        print(f"Default voice ID: {current_voice}")

    engine.say(text)
    engine.runAndWait()

if __name__ == "__main__":
    try:
        engine = pyttsx3.init()
    except Exception as e:
        print(f"Failed to initialize pyttsx3. Error: {e}")
        print("Please ensure you have a text-to-speech engine (like SAPI5 on Windows) installed and configured correctly.")
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
