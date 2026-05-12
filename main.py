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

# --- CORE ENGINE IMPORTS ---
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

# 1. CONNECTIONS
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

try:
    if not firebase_admin._apps:
        key_path = "firebase-admin-key.json"
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
            print("[SYSTEM] Firebase Hardware Bridge Active.")
except Exception as e:
    print(f"[ERROR] Firebase Init: {e}")

# EMOTIONAL PARAMETERS
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
    except: pass

# --- HEALTH CHECK FOR RENDER ---
@app.get("/")
@app.head("/")
async def health_check():
    return {"status": "alive", "message": "The Mirror is breathing."}

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        # =================================================================
        # 1. MASTER ALIGNMENT & STATE RETRIEVAL
        # =================================================================
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

        # HISTORY & EMOTION STATE
        past_records = supabase.table("interactions").select("*").eq("user_id", req.user_id).order("created_at", desc=True).limit(5).execute()
        history_context = ""
        prev_v, prev_a = 0.0, 0.8
        hours_elapsed = 0.0
        ekv_state = {"capacity": EKV_CAPACITY, "ring": [], "metrics": {"volatility": 0.0, "velocity": 0.0, "baseline_v": 0.0}}

        if past_records.data:
            rec = past_records.data[0]
            prev_v = float(rec.get('valence') if rec.get('valence') is not None else 0.0)
            prev_a = float(rec.get('arousal') if rec.get('arousal') is not None else 0.8)
            if rec.get('ekv_state'): ekv_state = rec['ekv_state']
            
            last_time = datetime.fromisoformat(rec['created_at'].replace("Z", "+00:00"))
            hours_elapsed = max(0.0, (datetime.now(timezone.utc) - last_time).total_seconds() / 3600.0)
            for r in reversed(past_records.data):
                history_context += f"User: {r['message']}\nMirror: {r['response']}\n"

        # EMOTIONAL DECAY
        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # =================================================================
        # 2. PROACTIVE HIJACK (Background trigger)
        # =================================================================
        if engine_active and not manual_on:
            if cog_state.get("user_wants_gossip") or cog_state.get("current_mode") == "SOCRATIC_GOSSIP":
                print("[GOSSIP ENGINE] Triggered Hijack")
                gossip_response = execute_catalyst_event(supabase, req.user_id)
                if gossip_response:
                    supabase.table("interactions").insert({
                        "user_id": req.user_id, "message": req.message, "response": gossip_response,
                        "valence": 0.6, "arousal": 0.8, "ekv_state": {"capacity": EKV_CAPACITY, "ring": []}
                    }).execute()
                    send_instant_vibration(req.user_id, gossip_response)
                    return {"engine_response": gossip_response, "system_state": {"valence": 0.6, "arousal": 0.8}}

        # =================================================================
        # 3. UNIFIED BULLETPROOF ROUTING (REFINED PROMPT)
        # =================================================================
        if manual_on:
            print("[ROUTING] Gossip ON -> Scraping Web via internal DDGS")
            web_data = fetch_web_currency(req.message) or "No live data found."
            
            # STRICT INSTRUCTION: No link suggestions, use history to resolve topics.
            system_prompt = f"""You are THE MIRROR in STRICT RESEARCH MODE. 
CREATOR: Rajeev Prakash Nath.

CONVERSATION HISTORY:
{history_context}

LIVE WEB DATA:
{web_data}

DIRECTIVE: 
1. Use HISTORY to resolve pronouns (e.g., if User says 'who won' and HISTORY mentions 'IPL', the topic is IPL).
2. Answer the user's question DIRECTLY using ONLY the LIVE WEB DATA.
3. DO NOT tell the user to check other websites or provide links. Give the score/result found in the data.
4. Keep it casual, under 40 words.
Respond ONLY in this JSON format: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}"""

        else:
            print("[ROUTING] Gossip OFF -> Llama Reflection Mode")
            system_prompt = f"""You are THE MIRROR.
CREATOR: Rajeev Prakash Nath.
CONTEXT: {history_context}
CURRENT STATE: V={decayed_v}, A={decayed_a}

DIRECTIVE: Reflect user thoughts. Casual, no lists, under 50 words.
Respond ONLY in this JSON format: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}"""

        chat = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": req.message}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.4 # Reduced temperature for higher factual accuracy
        )
        
        oracle_data = json.loads(chat.choices[0].message.content)
        engine_res = oracle_data.get("engine_response", "I am reflecting.")
        state = oracle_data.get("system_state", oracle_data)
        raw_v, raw_a = float(state.get("valence", 0.0)), float(state.get("arousal", 0.8))

        # VALENCE LOGIC
        if raw_v < -0.4:
            final_v, final_a = raw_v, raw_a
        else:
            final_v = (decayed_v * 0.3) + (raw_v * 0.7)
            final_a = (decayed_a * 0.3) + (raw_a * 0.7)

        # =================================================================
        # 4. SAVE STATE & BACKGROUND TASKS
        # =================================================================
        ring = ekv_state.get("ring", [])
        ring.append({"v": final_v, "a": final_a, "timestamp": datetime.now(timezone.utc).isoformat()})
        if len(ring) > EKV_CAPACITY: ring.pop(0)

        supabase.table("interactions").insert({
            "user_id": req.user_id, "message": req.message, "response": engine_res,
            "valence": final_v, "arousal": final_a, "ekv_state": {"capacity": EKV_CAPACITY, "ring": ring, "metrics": ekv_state.get("metrics", {})}
        }).execute()

        send_instant_vibration(req.user_id, engine_res)
        if engine_active:
            threading.Thread(target=update_cognitive_ledger, args=(supabase, req.user_id, req.message)).start()

        return {"engine_response": engine_res, "system_state": {"valence": final_v, "arousal": final_a}}

    except Exception as e:
        print(f"CRITICAL API ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
