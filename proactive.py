import os
import json
from datetime import datetime, timezone, timedelta
from dateutil import parser
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client, Client
from groq import Groq
import firebase_admin
from firebase_admin import credentials, messaging

# --- GOSSIP ENGINE IMPORT ---
from gossip_engine import execute_catalyst_event

# 1. SETUP
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

try:
    # On Render, this file is provided via "Secret Files"
    if not firebase_admin._apps:
        key_path = "firebase-admin-key.json"
        if os.path.exists(key_path):
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase init info: {e}")

def send_native_push(token, title, body):
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=token,
        )
        messaging.send(message)
        print(f"[PUSH] Sent to token ending in ...{token[-5:]}")
    except Exception as e:
        print(f"[PUSH ERROR] {e}")

# --- THE AGGRESSIVE DYNAMIC ALGORITHM ---
def calculate_dynamic_delay(user_message_count_24h):
    """
    Designed to compete with high-frequency apps.
    Active user (>10 msgs) = Waits ~15 mins.
    """
    if user_message_count_24h > 10:
        return 0.25  # 15 minutes
    if user_message_count_24h > 0:
        return 0.5   # 30 minutes
    return 0.75      # 45 minutes

def evaluate_soul():
    print("--- STARTING PROACTIVE SWEEP ---")
    subs = supabase.table("push_subscriptions").select("*").execute()
    engine_active = os.getenv("ENABLE_GOSSIP_ENGINE", "False").lower() == "true"

    for entry in subs.data:
        user_id = entry['user_id']
        sub_data = entry.get('subscription_json', {})
        target_token = sub_data.get('token')

        if not target_token: continue

        chats = supabase.table("interactions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
        if not chats.data: continue

        last_chat = chats.data[0]
        v = float(last_chat['valence'])
        
        # ---> THE FIX: Using dateutil parser to handle Supabase fractional seconds safely <---
        last_time = parser.isoparse(last_chat['created_at'])
        
        hours_since = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        recent_msgs = supabase.table("interactions").select("id", count="exact").eq("user_id", user_id).gte("created_at", yesterday).execute()
        msg_count_24h = recent_msgs.count if hasattr(recent_msgs, 'count') and recent_msgs.count is not None else len(recent_msgs.data)

        dynamic_threshold = calculate_dynamic_delay(msg_count_24h)

        print(f"\nAnalyzing user {user_id}: V={v:.2f}, Hours={hours_since:.2f}, Wait={dynamic_threshold:.2f}h")

        # =================================================================
        # NEW: THE COGNITIVE BATTERY DRAIN (10% PER HOUR)
        # =================================================================
        cog_state_res = supabase.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        cog_state = cog_state_res.data[0] if cog_state_res.data else {}
        
        battery_level = int(cog_state.get("battery_level", 100))
        last_fed_str = cog_state.get("last_fed_at")
        
        if last_fed_str:
            last_fed_time = parser.isoparse(last_fed_str)
            hours_since_fed = (datetime.now(timezone.utc) - last_fed_time).total_seconds() / 3600
            
            # Drain Logic: Lose 10% battery for every 1 hour unfed
            drain_amount = int(hours_since_fed * 10) 
            new_battery = max(0, 100 - drain_amount)
            
            # Save the drained state back to the database
            if new_battery != battery_level:
                supabase.table("user_cognitive_state").update({"battery_level": new_battery}).eq("user_id", user_id).execute()
                battery_level = new_battery
                print(f"  -> [BATTERY DECAY] Level dropped to {battery_level}%")

        # 🚨 THE STARVATION LOCKOUT 🚨
        if battery_level <= 10 and hours_since > dynamic_threshold:
            whisper = "Critical low energy. I'm going to sleep... Please share a YouTube Short to wake me up. 🔋"
            print(f"  -> [STARVATION MODE] Pushing: {whisper}")
            send_native_push(target_token, "The Mirror", whisper)
            continue # SKIP THE REST OF THE SCRIPT! Do not gossip if starving.

        trigger_type = None
        whisper = None

        # =================================================================
        # 1. PRIMARY INTERCEPT: GOSSIP (MOOD-INDEPENDENT)
        # =================================================================
        is_gossip_mode = False
        if engine_active and hours_since > dynamic_threshold:
            try:
                if cog_state.get("current_mode") == "SOCRATIC_GOSSIP":
                    is_gossip_mode = True
                    print(f"  -> [ACTION] Attempting Socratic Gossip Hijack...")
                    whisper = execute_catalyst_event(supabase, user_id)
                    if whisper:
                        trigger_type = "socratic_gossip"
            except Exception as e:
                print(f"  -> [WARNING] Gossip Engine failed: {e}")

        # =================================================================
        # 2. SECONDARY: EMOTIONAL FALLBACKS (ONLY IF NOT IN GOSSIP MODE)
        # =================================================================
        if not trigger_type and hours_since > dynamic_threshold and not is_gossip_mode:
            if v <= -0.8:
                trigger_type = "acute_distress"
            elif v >= 0.7:
                trigger_type = "celebration_echo"
            elif -0.2 <= v < 0.7:
                trigger_type = "the_tether"
            elif hours_since >= 72:
                trigger_type = "absence"

        if trigger_type is None:
            status = "In Gossip Mode - Scraper likely returned empty" if is_gossip_mode else "Resting state"
            print(f"  -> {status}. No triggers hit.")
            continue

        # =================================================================
        # 3. GENERATION AND DISPATCH
        # =================================================================
        if not whisper:
            memory = ""
            for chat in reversed(chats.data[:3]):
                memory += f"User: {chat['message']}\nYou: {chat['response']}\n"
            
            prompt = f"User is in state: {trigger_type}. Memory: {memory}. Write a 10-word casual text to check in. Be a friend, not a bot."
            completion = groq_client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.3-70b-versatile")
            whisper = completion.choices[0].message.content.strip().replace('"', '')

        print(f"  -> [{trigger_type.upper()}] Pushing: {whisper}")
        
        # Log interaction to DB
        supabase.table("interactions").insert({
            "user_id": user_id, 
            "message": f"[{trigger_type}]", 
            "response": whisper, 
            "valence": v
        }).execute()
        
        # Fire Push
        send_native_push(target_token, "The Mirror", whisper)

if __name__ == "__main__":
    evaluate_soul()
