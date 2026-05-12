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

# --- NEW: GOOGLE GENAI IMPORT ---
from google import genai
from google.genai import types

# --- GOSSIP ENGINE IMPORTS ---
from gossip_engine import execute_catalyst_event
from cognitive_observer import update_cognitive_ledger

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

# --- NEW SDK GEMINI SETUP ---
gemini_api_key = os.environ.get("GEMINI_API_KEY")
gemini_client = None
if gemini_api_key:
    gemini_client = genai.Client(api_key=gemini_api_key)
    print("[SYSTEM] Gemini AI (Web Search) Active via google-genai.")
else:
    print("[WARNING] GEMINI_API_KEY not found in environment.")

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
        # =================================================================
        # 1. FETCH COGNITIVE STATE & HISTORY
        # =================================================================
        cog_state = {}
        cog_state_res = supabase.table("user_cognitive_state").select("*").eq("user_id", req.user_id).execute()
        if cog_state_res.data:
            cog_state = cog_state_res.data[0]
            
        manual_gossip_mode = cog_state.get("manual_gossip_toggle", False)
        engine_active = os.getenv("ENABLE_GOSSIP_ENGINE", "False").lower() == "true"

        history_context = ""
        prev_v, prev_a = 0.0, 0.8
        hours_elapsed = 0.0
        ekv_state = {"capacity": EKV_CAPACITY, "ring": [], "metrics": {"volatility": 0.0, "velocity": 0.0, "baseline_v": 0.0}}

        past_records = supabase.table("interactions").select("*").eq("user_id", req.user_id).order("created_at", desc=True).limit(5).execute()

        if past_records.data:
            rec = past_records.data[0]
            prev_v = float(rec.get('valence') if rec.get('valence') is not None else 0.0)
            prev_a = float(rec.get('arousal') if rec.get('arousal') is not None else 0.8)
            if rec.get('ekv_state'): ekv_state = rec['ekv_state']
            last_time_str = rec.get('created_at')
            if last_time_str:
                last_time = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
                hours_elapsed = max(0.0, (datetime.now(timezone.utc) - last_time).total_seconds() / 3600.0)
            for r in reversed(past_records.data):
                history_context += f"User: {r['message']}\nMirror: {r['response']}\n"

        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # =================================================================
        # 2. PROACTIVE HIJACK (Background trigger)
        # =================================================================
        if engine_active and not manual_gossip_mode:
            try:
                if cog_state.get("user_wants_gossip") == True or cog_state.get("current_mode") == "SOCRATIC_GOSSIP":
                    print("[GOSSIP ENGINE] Intent Route Triggered!")
                    gossip_response = execute_catalyst_event(supabase, req.user_id)
                    if gossip_response:
                        supabase.table("interactions").insert({
                            "user_id": req.user_id, "message": req.message, "response": gossip_response,
                            "valence": 0.6, "arousal": 0.8, "ekv_state": {"capacity": EKV_CAPACITY, "ring": []}
                        }).execute()
                        send_instant_vibration(req.user_id, gossip_response)
                        return {"engine_response": gossip_response, "system_state": {"valence": 0.6, "arousal": 0.8}}
            except Exception as e:
                print(f"[ERROR] Engine routing failed safely: {e}")


        # =================================================================
        # 3. CORE ROUTING (GEMINI vs GROQ)
        # =================================================================
        engine_res = ""
        final_v, final_a = decayed_v, decayed_a

        # --- BRANCH A: GOSSIP MODE (GEMINI WEB SEARCH) ---
        if manual_gossip_mode and gemini_client:
            print("[SYSTEM] Routing to Gemini (Search Grounded)")
            try:
                sys_instruct = "You are THE MIRROR in GOSSIP/RESEARCH mode. Use Google Search to find the latest real-time data to answer the user."
                
                # New SDK syntax for Search Grounding
                chat_response = gemini_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"{sys_instruct}\n\nUser: {req.message}",
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())]
                    )
                )
                engine_res = chat_response.text
                final_a = min(1.0, decayed_a + 0.2) 
            except Exception as e:
                print(f"[ERROR] Gemini search failed: {e}. Falling back to Groq.")
                manual_gossip_mode = False 

        # --- BRANCH B: NORMAL CHAT (GROQ) ---
        if not manual_gossip_mode or not gemini_client:
            print("[SYSTEM] Routing to Groq (Normal Chat)")
            system_prompt = f"""You are THE MIRROR.
CREATOR: Developed by Rajeev Prakash Nath.
CONTEXT: {history_context}
CURRENT STATE: V={decayed_v}, A={decayed_a}
DIRECTIVE: Analyze message for valence score.
Respond ONLY in this JSON format: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}"""

            chat = groq_client.chat.completions.create(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
                model="llama-3.3-70b-versatile",
                response_format={"type": "json_object"}
            )
            oracle_data = json.loads(chat.choices[0].message.content)
            engine_res = oracle_data.get("engine_response", "I am reflecting on that.")
            
            state = oracle_data.get("system_state", oracle_data)
            raw_v = float(state.get("valence", 0.0))
            raw_a = float(state.get("arousal", 0.8))

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
            "valence": final_v, "arousal": final_a, "ekv_state": {"capacity": EKV_CAPACITY, "ring": ring}
        }).execute()

        send_instant_vibration(req.user_id, engine_res)

        if engine_active:
            threading.Thread(target=update_cognitive_ledger, args=(supabase, req.user_id, req.message)).start()

        return {"engine_response": engine_res, "system_state": {"valence": final_v, "arousal": final_a}}

    except Exception as e:
        print(f"CRITICAL API ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
