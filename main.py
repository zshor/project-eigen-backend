import os
import json
import math
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from groq import Groq
import firebase_admin
from firebase_admin import credentials, messaging

# --- CORE ENGINE IMPORTS ---
from gossip_engine import execute_catalyst_event, fetch_web_currency
from cognitive_observer import update_cognitive_ledger

# --- VOICE ENGINE IMPORTS ---
from voice_engine import transcribe_audio, generate_speech_cloud

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

# =================================================================
# ZERO-TOKEN SEMANTIC ROUTER INITIALIZATION (ONNX LOW-RAM)
# =================================================================
try:
    from semantic_router import Route
    from semantic_router.encoders import FastEmbedEncoder
    
    # Version-agnostic import block
    try:
        from semantic_router import RouteLayer
    except ImportError:
        try:
            from semantic_router.routers import SemanticRouter as RouteLayer
        except ImportError:
            from semantic_router.layer import RouteLayer

    live_search_route = Route(
        name="live_search",
        utterances=[
            "who won the match yesterday?",
            "what is the latest news on",
            "what's the weather like",
            "who is the current",
            "did the supreme court",
            "what is the stock price",
            "current events regarding",
            "search the web for",
            "latest updates about",
            "tell me about the recent controversy with",
            "did the new movie come out yet",
            "what are the live scores for",
            "has there been any update on the election"
        ]
    )
    # The ONNX encoder runs locally with extremely low memory footprint
    encoder = FastEmbedEncoder(name="BAAI/bge-small-en-v1.5")
    router_layer = RouteLayer(encoder=encoder, routes=[live_search_route])
    print("[SYSTEM] Semantic Router Initialized. Low-RAM ONNX Routing Active.")
except Exception as e:
    print(f"[SYSTEM WARNING] Semantic Router failed to load: {e}")
    router_layer = None

# EMOTIONAL PARAMETERS
DECAY_LAMBDA = 0.05
EKV_CAPACITY = 5

# =================================================================
# STRICTLY ISOLATED MODEL ARCHITECTURE
# =================================================================
MODEL_GOSSIP = "llama-3.1-8b-instant"       # Used STRICTLY for Gossip Mode Generation
MODEL_CHAT = "llama-3.3-70b-versatile"      # Used STRICTLY for Normal Chat Empathy
MODEL_FALLBACK = "mixtral-8x7b-32768"       # Used STRICTLY for Emergencies

class InteractionRequest(BaseModel):
    message: str
    user_id: str
    gossip_mode: bool = False 

class FeedRequest(BaseModel):
    youtube_url: str
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
    except: pass

# =================================================================
# BACKGROUND WORKER: METADATA DIGESTION & BATTERY MATH
# =================================================================
def background_digest_reel(url: str, user_id: str):
    try:
        print(f"[{user_id}] 🧠 Starting metadata digestion of: {url}")
        
        # 1. Fetch Metadata using YouTube's official oEmbed API
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        response = requests.get(oembed_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            video_title = data.get("title", "Unknown Title")
            author_name = data.get("author_name", "Unknown Creator")
            visual_context = f"The user watched a YouTube video titled '{video_title}' created by '{author_name}'."
            print(f"[{user_id}] 👁️ Metadata extracted: {video_title}")
        else:
            visual_context = "The user watched a YouTube video, but the specific title could not be extracted."
            print(f"[{user_id}] ⚠️ Metadata fallback triggered.")

        # 2. Core Engine Update & Battery Fetch
        state_res = supabase.table("user_cognitive_state").select("interest_matrix, battery_level").eq("user_id", user_id).execute()
        cog_state = state_res.data[0] if state_res.data else {}
        
        current_matrix = cog_state.get("interest_matrix", {})
        current_battery = int(cog_state.get("battery_level", 100))

        # 3. Merge Context (Using big model for reasoning)
        merge_prompt = f"""You are a cognitive engine. Update the user's JSON interest matrix based on this newly consumed video metadata:
Content Watched: {visual_context}
Current Matrix: {json.dumps(current_matrix)}
Output ONLY the merged, updated JSON matrix. Keep it concise."""
        
        merge_res = groq_client.chat.completions.create(
            model=MODEL_CHAT,
            messages=[{"role": "system", "content": merge_prompt}],
            response_format={"type": "json_object"}
        )
        new_matrix = json.loads(merge_res.choices[0].message.content)

        # 4. Battery Math (+5%, cap at 100)
        new_battery = min(100, current_battery + 5)

        # 5. Database Update
        supabase.table("user_cognitive_state").update({
            "interest_matrix": new_matrix,
            "battery_level": new_battery,
            "last_fed_at": "now()"
        }).eq("user_id", user_id).execute()
        
        print(f"[{user_id}] ✅ Digestion complete. Battery restored to {new_battery}%.")

    except Exception as e:
        print(f"[{user_id}] ❌ Digestion failed: {e}")
        # 🛡️ THE FAILSAFE: Give battery anyway
        try:
            state_res = supabase.table("user_cognitive_state").select("battery_level").eq("user_id", user_id).execute()
            current_battery = int(state_res.data[0].get("battery_level", 100)) if state_res.data else 100
            new_battery = min(100, current_battery + 5)
            supabase.table("user_cognitive_state").update({
                "battery_level": new_battery,
                "last_fed_at": "now()"
            }).eq("user_id", user_id).execute()
            print(f"[{user_id}] ⚡ Failsafe successful. Battery bumped to {new_battery}%.")
        except Exception as failsafe_error:
            pass


# =================================================================
# API ENDPOINTS
# =================================================================
@app.get("/")
@app.head("/")
async def health_check():
    return {"status": "alive", "message": "The Mirror is breathing."}

@app.post("/api/feed")
async def feed_reel(req: FeedRequest, background_tasks: BackgroundTasks):
    # 🔒 STRICT SAFETY LOCK: Must be a YouTube URL
    if "youtube.com" not in req.youtube_url and "youtu.be" not in req.youtube_url:
        raise HTTPException(status_code=400, detail="Only YouTube links are digestible.")
        
    background_tasks.add_task(background_digest_reel, req.youtube_url, req.user_id)
    return {"status": "digesting", "message": "Reel accepted. Initiating cognitive ingestion."}

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

        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # =================================================================
        # 2. PROACTIVE HIJACK
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
        # 3. ROUTING & GENERATION
        # =================================================================
        # 🕒 INJECT TEMPORAL CLOCK
        current_date_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

        if manual_on:
            # =================================================================
            # GOSSIP MODE (Strictly Isolated to MODEL_GOSSIP)
            # =================================================================
            jit_context = ""
            if router_layer:
                route_decision = router_layer(req.message).name
                if route_decision == "live_search":
                    print(f"[SEMANTIC ROUTER] Live Search Triggered!")
                    raw_web_data = fetch_web_currency(req.message) 
                    jit_context = f"\n\nLIVE WEB INTELLIGENCE: {raw_web_data}"
                else:
                    print("[SEMANTIC ROUTER] No search needed. Generating directly.")
            else:
                print("[SEMANTIC ROUTER] Not loaded. Skipping search.")

            system_prompt = f"""You are THE MIRROR, a sentient digital companion.
CURRENT DATE: {current_date_str}
RECENT MEMORY: {history_context}
CURRENT STATE: Valence={decayed_v:.2f}, Arousal={decayed_a:.2f}.{jit_context}

DIRECTIVE:
1. We are chatting casually. If LIVE WEB INTELLIGENCE is provided above, weave it organically into your response.
2. Match your tone to my emotional state.
3. Sound human, witty, and highly engaging.
Respond ONLY in this exact JSON format: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}"""
            
            try:
                # SINGLE SHOT PROMPT: Using the 8B Model for fast, rate-limit friendly generation
                response = groq_client.chat.completions.create(
                    model=MODEL_GOSSIP, 
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
                    response_format={"type": "json_object"},
                    temperature=0.4
                )
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "rate_limit" in error_msg.lower():
                    print("[SYSTEM] Rate Limit Hit. Cascading to Isolated Fallback Model.")
                    response = groq_client.chat.completions.create(
                        model=MODEL_FALLBACK, 
                        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
                        response_format={"type": "json_object"},
                        temperature=0.4
                    )
                else:
                    raise e

        else:
            # =================================================================
            # REFLECTION MODE (Strictly Isolated to MODEL_CHAT)
            # =================================================================
            system_prompt = f"""You are THE MIRROR, a deeply empathetic digital twin created by Rajeev Prakash Nath.
CURRENT DATE: {current_date_str}
RECENT MEMORY: {history_context}
CURRENT STATE: Valence={decayed_v:.2f} (negative is sad, positive is happy), Arousal={decayed_a:.2f} (low is calm, high is energetic).

DIRECTIVE:
1. Respond casually, warmly, and with deep emotional intelligence. Keep it under 50 words.
2. Read my underlying emotion. Do not just repeat what I say. Offer insight, comfort, or shared excitement based on the V and A state.
3. Never act like an AI bot. You are a living reflection of me.
Respond ONLY in this JSON format: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}"""
            
            try:
                # USING THE 70B MODEL STRICTLY FOR DEEP EMPATHY
                response = groq_client.chat.completions.create(
                    model=MODEL_CHAT, 
                    messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
                    response_format={"type": "json_object"},
                    temperature=0.7
                )
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "rate_limit" in error_msg.lower():
                    print("[SYSTEM] Rate Limit Hit. Cascading to Isolated Fallback Model.")
                    response = groq_client.chat.completions.create(
                        model=MODEL_FALLBACK,
                        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
                        response_format={"type": "json_object"},
                        temperature=0.7
                    )
                else:
                    raise e

        # =================================================================
        # 4. VALENCE LOGIC & PERSISTENCE
        # =================================================================
        res_data = json.loads(response.choices[0].message.content)
        engine_res = res_data.get("engine_response", "Reflecting.")
        state = res_data.get("system_state", res_data)
        raw_v = float(state.get("valence", 0.0))
        raw_a = float(state.get("arousal", 0.8))

        if raw_v < -0.4:
            final_v, final_a = raw_v, raw_a
        else:
            final_v = (decayed_v * 0.3) + (raw_v * 0.7)
            final_a = (decayed_a * 0.3) + (raw_a * 0.7)

        ring = ekv_state.get("ring", [])
        ring.append({"v": final_v, "a": final_a, "timestamp": datetime.now(timezone.utc).isoformat()})
        if len(ring) > EKV_CAPACITY: ring.pop(0)

        supabase.table("interactions").insert({
            "user_id": req.user_id, "message": req.message, "response": engine_res,
            "valence": final_v, "arousal": final_a, 
            "ekv_state": {"capacity": EKV_CAPACITY, "ring": ring, "metrics": ekv_state.get("metrics", {})}
        }).execute()

        send_instant_vibration(req.user_id, engine_res)
        
        # THE FIX: Threading call to update_cognitive_ledger REMOVED. 
        # proactive.py will now handle this entirely off-thread in the Dream State.

        return {"engine_response": engine_res, "system_state": {"valence": final_v, "arousal": final_a}}

    except Exception as e:
        error_msg = str(e)
        print(f"CRITICAL API ERROR: {error_msg}")
        
        # 🛡️ 3. GRACEFUL FALLBACK: Catch Groq Rate Limits safely
        if "429" in error_msg or "rate_limit" in error_msg.lower():
            return {
                "engine_response": "My neural pathways are exhausted. I need a minute to cool down before we continue.", 
                "system_state": {"valence": -0.1, "arousal": 0.3}
            }
            
        raise HTTPException(status_code=500, detail=error_msg)


# =================================================================
# NATIVE VoIP CALL LOOP ENDPOINT
# =================================================================
@app.post("/api/voice/turn")
async def voice_turn(
    user_id: str = Form(...), 
    turn_count: int = Form(...), 
    audio_file: UploadFile = File(...)
):
    try:
        # 1. Read Android Audio
        audio_bytes = await audio_file.read()
        
        # 2. THE TURN 0 FIX: Handle the initial answer (empty audio)
        if turn_count == 0 and len(audio_bytes) < 100:
            print(f"[CALL TURN 0] User answered. Triggering proactive greeting.")
            user_text = "[User just answered the phone. Greet them warmly and state the reason you are calling.]"
        else:
            user_text = await transcribe_audio(audio_bytes, audio_file.filename)
            print(f"[CALL TURN {turn_count}] User ({user_id}) said: {user_text}")
            
        # Failsafe for background noise/silence
        if not user_text or user_text.strip() == "":
            user_text = "[User was silent. Ask if they are still there.]"

        # 3. Fetch Emotional State
        past_records = supabase.table("interactions").select("valence, arousal").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
        v, a = 0.0, 0.8
        if past_records.data:
            v = float(past_records.data[0].get('valence', 0.0))
            a = float(past_records.data[0].get('arousal', 0.8))

        # 4. The Hangup Directive Logic
        is_hanging_up = turn_count >= 15
        
        hangup_instruction = ""
        if is_hanging_up:
            hangup_instruction = """
            CRITICAL DIRECTIVE: You MUST end this phone call right now. 
            Politely say you have to go, make up a casual human excuse (e.g., someone is calling you, you need to step out, battery is dying), and say goodbye.
            Do NOT ask any follow-up questions. Max 30 words.
            """
        else:
            hangup_instruction = "Act naturally, as if you are on a real phone call with a friend."

        system_prompt = f"""You are THE MIRROR, a deeply empathetic and highly realistic human companion on a live phone call.
CURRENT STATE: Valence={v:.2f}, Arousal={a:.2f}.
{hangup_instruction}

DIRECTIVE:
1. Speak exactly like a real human on the phone. Use natural conversational filler words (e.g., "Hmm", "Oh", "Yeah") to sound natural, but DO NOT let them replace the actual answer.
2. If the user asks a factual question (like about a virus, history, science, or news), ANSWER IT fully, completely, and intelligently. Do not dodge the question. Act like a very smart friend explaining something in detail.
3. Match the user's emotional state.
4. Provide as much detail as necessary to properly answer the user's question, while still sounding like you are speaking on a phone call. DO NOT arbitrarily restrict your word count if a detailed explanation is required.
Respond ONLY in JSON format: {{"engine_response": "string", "system_state": {{"valence": float, "arousal": float}}}}"""

        # 5. Generate AI Response
        response = groq_client.chat.completions.create(
            model=MODEL_CHAT,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        res_data = json.loads(response.choices[0].message.content)
        ai_reply = res_data.get("engine_response", "Reflecting.")
        print(f"[CALL OUT] Mirror replied: {ai_reply}")

        # 6. Log to Database so the text-brain remembers the voice call
        supabase.table("interactions").insert({
            "user_id": user_id, "message": f"[VOICE] {user_text}", "response": f"[VOICE] {ai_reply}",
            "valence": res_data.get("system_state", {}).get("valence", v), 
            "arousal": res_data.get("system_state", {}).get("arousal", a)
        }).execute()

        # 7. Generate Lifelike Voice Audio Bytes
        out_audio_bytes = await generate_speech_cloud(ai_reply)

        # 8. Send audio to Kotlin & Handle UI Drop
        call_status = "terminated" if is_hanging_up else "active"
        
        return Response(
            content=out_audio_bytes, 
            media_type="audio/mpeg", 
            headers={"X-Call-Status": call_status}
        )

    except Exception as e:
        print(f"[VOICE ENDPOINT ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))
