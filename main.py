import os
import json
import math
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from groq import Groq
import firebase_admin
from firebase_admin import credentials, messaging

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. SETUP CONNECTIONS
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# 2. FIREBASE HARDWARE BRIDGE
try:
    if not firebase_admin._apps:
        key_path = "firebase-admin-key.json"
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            print("[SYSTEM] Firebase Hardware Bridge Active.")
except Exception as e:
    print(f"[ERROR] Firebase Init: {e}")

DECAY_LAMBDA = 0.05 
EKV_CAPACITY = 5    

class InteractionRequest(BaseModel):
    message: str
    user_id: str

def send_instant_vibration(user_id, text):
    try:
        res = supabase.table("push_subscriptions").select("subscription_json").eq("user_id", user_id).execute()
        if res.data:
            token = res.data[0]['subscription_json'].get('token')
            if token:
                message = messaging.Message(
                    notification=messaging.Notification(title="The Mirror", body=text),
                    token=token
                )
                messaging.send(message)
    except Exception as e:
        print(f"Push skipped: {e}")

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        history_context = ""
        prev_v, prev_a = 0.0, 0.8
        hours_elapsed = 0.0
        ekv_state = {"capacity": EKV_CAPACITY, "ring": [], "metrics": {"volatility": 0.0, "velocity": 0.0, "baseline_v": 0.0}}
        
        past_records = supabase.table("interactions").select("*").eq("user_id", req.user_id).order("created_at", desc=True).limit(5).execute()
        
        if past_records.data:
            # SAFE LOADING: Use .get() with a default value to prevent 'NoneType' errors
            rec = past_records.data[0]
            prev_v = float(rec.get('valence') if rec.get('valence') is not None else 0.0)
            prev_a = float(rec.get('arousal') if rec.get('arousal') is not None else 0.8)
            
            if rec.get('ekv_state'):
                ekv_state = rec['ekv_state']
            
            last_time_str = rec.get('created_at')
            if last_time_str:
                last_time = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
                hours_elapsed = max(0.0, (datetime.now(timezone.utc) - last_time).total_seconds() / 3600.0)
            
            for r in reversed(past_records.data):
                history_context += f"User: {r['message']}\nMirror: {r['response']}\n"

        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        system_prompt = f"""You are THE MIRROR. 
CREATOR: Developed by Rajeev Prakash Nath.
CONTEXT: {history_context}
CURRENT STATE: V={decayed_v}, A={decayed_a}
DIRECTIVE: Analyze message for valence score. JSON ONLY. 
- Deep grief: Valence -0.7 to -1.0."""

        chat = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )

        oracle_data = json.loads(chat.choices[0].message.content)
        raw_v = float(oracle_data["system_state"]["valence"])
        raw_a = float(oracle_data["system_state"]["arousal"])

        if raw_v < -0.4:
            final_v, final_a = raw_v, raw_a
        else:
            final_v = (decayed_v * 0.3) + (raw_v * 0.7)
            final_a = (decayed_a * 0.3) + (raw_a * 0.7)
        
        ring = ekv_state.get("ring", [])
        ring.append({"v": final_v, "a": final_a, "timestamp": datetime.now(timezone.utc).isoformat()})
        if len(ring) > EKV_CAPACITY: ring.pop(0)
            
        supabase.table("interactions").insert({
            "user_id": req.user_id, "message": req.message, "response": oracle_data["engine_response"],
            "valence": final_v, "arousal": final_a, "ekv_state": {"capacity": EKV_CAPACITY, "ring": ring}
        }).execute()

        send_instant_vibration(req.user_id, oracle_data["engine_response"])

        return {"engine_response": oracle_data["engine_response"], "system_state": {"valence": final_v, "arousal": final_a}}

    except Exception as e:
        print(f"CRITICAL API ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
