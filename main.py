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
import threading

from gossip_engine import execute_catalyst_event, fetch_web_currency
from cognitive_observer import update_cognitive_ledger

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. SETUP
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

try:
    if not firebase_admin._apps:
        key_path = "firebase-admin-key.json"
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Init: {e}")

DECAY_LAMBDA = 0.05
EKV_CAPACITY = 5

class InteractionRequest(BaseModel):
    message: str
    user_id: str
    gossip_mode: bool = False 

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
    except Exception as e: print(f"Push skipped: {e}")

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        # --- MASTER SYNC ---
        manual_on = req.gossip_mode
        supabase.table("user_cognitive_state").upsert({
            "user_id": req.user_id,
            "manual_gossip_toggle": manual_on,
            "current_mode": "SOCRATIC_GOSSIP" if manual_on else "NORMAL_CHAT",
            "user_wants_gossip": manual_on
        }, on_conflict="user_id").execute()

        cog_res = supabase.table("user_cognitive_state").select("*").eq("user_id", req.user_id).execute()
        cog_state = cog_res.data[0] if cog_res.data else {}
        engine_active = os.getenv("ENABLE_GOSSIP_ENGINE", "False").lower() == "true"

        # --- HISTORY & EMOTION ---
        past_records = supabase.table("interactions").select("*").eq("user_id", req.user_id).order("created_at", desc=True).limit(5).execute()
        history_context = ""
        prev_v, prev_a = 0.0, 0.8
        hours_elapsed = 0.0
        ekv_state = {"capacity": EKV_CAPACITY, "ring": []}

        if past_records.data:
            rec = past_records.data[0]
            prev_v = float(rec.get('valence', 0.0))
            prev_a = float(rec.get('arousal', 0.8))
            ekv_state = rec.get('ekv_state', ekv_state)
            last_time = datetime.fromisoformat(rec['created_at'].replace("Z", "+00:00"))
            hours_elapsed = max(0.0, (datetime.now(timezone.utc) - last_time).total_seconds() / 3600.0)
            for r in reversed(past_records.data):
                history_context += f"User: {r['message']}\nMirror: {r['response']}\n"

        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # --- PROACTIVE ---
        if engine_active and not manual_on:
            if cog_state.get("user_wants_gossip") or cog_state.get("current_mode") == "SOCRATIC_GOSSIP":
                g_res = execute_catalyst_event(supabase, req.user_id)
                if g_res:
                    supabase.table("interactions").insert({
                        "user_id": req.user_id, "message": req.message, "response": g_res,
                        "valence": 0.6, "arousal": 0.8, "ekv_state": {"capacity": EKV_CAPACITY, "ring": []}
                    }).execute()
                    send_instant_vibration(req.user_id, g_res)
                    return {"engine_response": g_res, "system_state": {"valence": 0.6, "arousal": 0.8}}

        # --- UNIFIED ROUTING ---
        web_context = ""
        if manual_on:
            web_context = fetch_web_currency(req.message) or "No live data found."

        system_prompt = f"""
        You are THE MIRROR. CONTEXT: {history_context}
        CURRENT STATE: V={decayed_v}, A={decayed_a}
        {"WEB RESEARCH DATA: " + web_context if manual_on else ""}
        Respond ONLY in JSON: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}
        """

        chat = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        
        oracle_data = json.loads(chat.choices[0].message.content)
        engine_res = oracle_data.get("engine_response", "Reflecting...")
        state = oracle_data.get("system_state", {"valence": 0.0, "arousal": 0.8})
        
        raw_v, raw_a = float(state.get("valence", 0.0)), float(state.get("arousal", 0.8))
        final_v = (decayed_v * 0.3) + (raw_v * 0.7)
        final_a = (decayed_a * 0.3) + (raw_a * 0.7)

        # --- SAVE & OBSERVE ---
        ring = ekv_state.get("ring", [])
        ring.append({"v": final_v, "a": final_a, "timestamp": datetime.now(timezone.utc).isoformat()})
        if len(ring) > EKV_CAPACITY: ring.pop(0)

        supabase.table("interactions").insert({
            "user_id": req.user_id, "message": req.message, "response": engine_res,
            "valence": final_v, "arousal": final_a, "ekv_state": {"capacity": EKV_CAPACITY, "ring": ring}
        }).execute()

        send_instant_vibration(req.user_id, engine_res)
        if engine_active:
            threading.Thread(target=update_cognitive_ledger, args=(supabase, req.user_id, req.message)).start()

        return {"engine_response": engine_res, "system_state": {"valence": final_v, "arousal": final_a}}

    except Exception as e:
        print(f"ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
