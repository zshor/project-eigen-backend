import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from supabase import create_client, Client

app = FastAPI()

# Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserMessage(BaseModel):
    user_id: str
    message: str

@app.post("/api/interact")
async def process_interaction(payload: UserMessage):
    try:
        # 1. Retrieve the Emotional KV Cache for this user
        # This is where the "Oracle" looks at who you WERE to decide who you ARE
        prev_state = supabase.table("interactions")\
            .select("valence, arousal")\
            .eq("user_id", payload.user_id)\
            .order("created_at", desc=True)\
            .limit(1).execute()
        
        # Default state if first time, otherwise use cached values
        last_valence = prev_state.data[0]['valence'] if prev_state.data else 0.0
        
        # 2. Generate the Mirror's Response
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": f"You are the Mirror. User's last known valence was {last_valence}. Adjust your coldness accordingly."},
                {"role": "user", "content": payload.message}
            ],
            model="llama-3.1-8b-instant",
        )
        engine_reply = chat_completion.choices[0].message.content

        # 3. Simple Emotional Math (The Oracle Forecasting Logic)
        # We will refine this math in the next step
        current_valence = last_valence - 0.1 if "not" in payload.message.lower() else last_valence + 0.1
        current_arousal = 0.8 # High focus for the Oracle Project

        # 4. Update the KV Cache (The Persistence Layer)
        supabase.table("interactions").insert({
            "user_id": payload.user_id,
            "message": payload.message,
            "response": engine_reply,
            "valence": current_valence,
            "arousal": current_arousal,
            "ekv_state": {"momentum": "calculating"}
        }).execute()

        return {
            "engine_response": engine_reply,
            "system_state": {"valence": current_valence, "arousal": current_arousal},
            "ui_directives": {"background_hex": "#0a0a0a" if current_valence < 0 else "#1a1a2e"}
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
