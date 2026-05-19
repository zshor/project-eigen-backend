import os
import edge_tts
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

async def transcribe_audio(file_bytes: bytes, filename="audio.m4a") -> str:
    """Instantly turns Android audio into text using Groq Whisper."""
    try:
        file_tuple = (filename, file_bytes)
        # 🛡️ THE FIX: Removed language="en" to allow Whisper to auto-detect Hindi/Hinglish!
        transcription = groq_client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3"
        )
        return transcription.text.strip()
    except Exception as e:
        print(f"[STT ERROR] Failed to transcribe: {e}")
        return ""

async def generate_speech_cloud(text: str) -> bytes:
    """Generates lifelike AI voice audio using zero server RAM."""
    if not text:
        return b""

    try:
        # 🛡️ THE FIX: 'hi-IN-SwaraNeural' is the native Hindi Female voice. 
        communicate = edge_tts.Communicate(text, "hi-IN-SwaraNeural")
        
        audio_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes += chunk["data"]
                
        return audio_bytes
    except Exception as e:
        print(f"[VOICE CRITICAL] Cloud TTS failed. Error: {e}")
        return b""
