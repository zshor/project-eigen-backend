import os
import json
import math
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from groq import Groq

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

DECAY_LAMBDA = 0.05 
EKV_CAPACITY = 5    

class InteractionRequest(BaseModel):
    message: str
    user_id: str

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        history_context = ""
        prev_v, prev_a = 0.0, 0.8
        hours_elapsed = 0.0
        ekv_state = {"capacity": EKV_CAPACITY, "ring": [], "metrics": {"volatility": 0.0, "velocity": 0.0, "baseline_v": 0.0}}
        
        past_records = supabase.table("interactions").select("*").eq("user_id", req.user_id).order("created_at", desc=True).limit(5).execute()
        
        if past_records.data:
            prev_v = float(past_records.data[0]['valence'])
            prev_a = float(past_records.data[0]['arousal'])
            if past_records.data[0].get('ekv_state'):
                ekv_state = past_records.data[0]['ekv_state']
            
            last_time = datetime.fromisoformat(past_records.data[0]['created_at'].replace("Z", "+00:00"))
            hours_elapsed = max(0.0, (datetime.now(timezone.utc) - last_time).total_seconds() / 3600.0)
            for rec in reversed(past_records.data):
                history_context += f"User: {rec['message']}\nMirror: {rec['response']}\n"

        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # UPDATED PROMPT: Forcing the AI to judge the USER'S EMOTION, not the overall chat vibe
        system_prompt = f"""You are THE MIRROR. 
CONTEXT: {history_context}
CURRENT STATE: V={decayed_v}, A={decayed_a}

DIRECTIVE: Analyze the USER'S MESSAGE ONLY for the valence score. 
- If they share death, grief, or extreme pain, Valence MUST be between -0.7 and -1.0.
- Do not let your own empathetic response "pull" the score back to neutral.
- Prioritize human comfort in your text response.

Respond ONLY in JSON: {{"engine_response": "...", "system_state": {{"valence": float, "arousal": float}}}}"""

        chat = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )

        oracle_data = json.loads(chat.choices[0].message.content)
        raw_v = float(oracle_data["system_state"]["valence"])
        raw_a = float(oracle_data["system_state"]["arousal"])

        # INSTANT OVERRIDE: If the AI detects deep sadness, we ignore the previous momentum entirely
        if raw_v < -0.4:
            final_v = raw_v
            final_a = raw_a
        else:
            final_v = (decayed_v * 0.3) + (raw_v * 0.7)
            final_a = (decayed_a * 0.3) + (raw_a * 0.7)
        
        new_entry = {"v": final_v, "a": final_a, "timestamp": datetime.now(timezone.utc).isoformat()}
        ring = ekv_state.get("ring", [])
        ring.append(new_entry)
        if len(ring) > EKV_CAPACITY: ring.pop(0)
            
        supabase.table("interactions").insert({
            "user_id": req.user_id, "message": req.message, "response": oracle_data["engine_response"],
            "valence": final_v, "arousal": final_a, "ekv_state": {"capacity": EKV_CAPACITY, "ring": ring}
        }).execute()

        return {"engine_response": oracle_data["engine_response"], "system_state": {"valence": final_v, "arousal": final_a}}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
