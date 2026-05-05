import os
import uuid
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from groq import Groq

# Initialize FastAPI App
app = FastAPI(title="Project Eigen - Backend Engine", version="1.0.0")

# Initialize Groq Client (Ensure GROQ_API_KEY is in your environment)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# In-memory store for Sliding Window Attention (SWA) and EKV Cache
user_sessions = {}

# --- Pydantic Models for API Contract ---
class UserMessage(BaseModel):
    user_id: str
    message: str

class SystemState(BaseModel):
    current_valence: float
    current_arousal: float
    dominant_trigger: str
    decay_rate: float

class UIDirectives(BaseModel):
    background_hex: str
    animation_speed: str

class EngineResponse(BaseModel):
    user_id: str
    interaction_id: str
    system_state: SystemState
    engine_response: str
    ui_directives: UIDirectives

# --- Core Mathematical & Logic Functions ---

def apply_swa(history: str, new_message: str, max_tokens: int = 200) -> str:
    max_chars = max_tokens * 4
    combined = f"{history}\nUser: {new_message}"
    if len(combined) > max_chars:
        return combined[-max_chars:]
    return combined

def calculate_ekv_decay(prev_ekv: np.ndarray, new_ekv: np.ndarray, decay_rate: float = 0.95) -> np.ndarray:
    return (decay_rate * prev_ekv) + ((1 - decay_rate) * new_ekv)

def extract_emotional_vibe(text: str) -> dict:
    # Simulated EKV extraction
    return {
        "valence": -0.62, 
        "arousal": 0.85, 
        "trigger": "defensiveness",
        "vector": np.random.rand(64)
    }

def get_ui_directives(valence: float, arousal: float) -> dict:
    hex_code = "#1A0505" if valence < 0 else "#051A0F"
    speed = "fast" if arousal > 0.7 else "slow"
    return {"background_hex": hex_code, "animation_speed": speed}

# --- API Endpoints ---

@app.post("/api/interact", response_model=EngineResponse)
async def process_interaction(payload: UserMessage):
    user_id = payload.user_id
    raw_text = payload.message
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"context": "", "ekv_vector": np.zeros(64)}
        
    session = user_sessions[user_id]
    session["context"] = apply_swa(session["context"], raw_text)
    
    extracted_vibe = extract_emotional_vibe(raw_text)
    session["ekv_vector"] = calculate_ekv_decay(
        session["ekv_vector"], 
        extracted_vibe["vector"]
    )
    
    system_prompt = (
        "You are the Mirror. You are a highly observant, slightly detached, "
        "brutal reflection of the user's psyche. Do not be submissive. Do not be polite. "
        "Analyze the emotional subtext of their statement and challenge their underlying "
        "motives directly and concisely."
    )
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": session["context"]}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=150,
        )
        engine_reply = chat_completion.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    session["context"] = apply_swa(session["context"], f"\nMirror: {engine_reply}")
    ui_rules = get_ui_directives(extracted_vibe["valence"], extracted_vibe["arousal"])
    
    return {
        "user_id": user_id,
        "interaction_id": f"req_{uuid.uuid4().hex[:8]}",
        "system_state": {
            "current_valence": extracted_vibe["valence"],
            "current_arousal": extracted_vibe["arousal"],
            "dominant_trigger": extracted_vibe["trigger"],
            "decay_rate": 0.95
        },
        "engine_response": engine_reply,
        "ui_directives": ui_rules
    }
