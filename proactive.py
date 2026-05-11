import os
import json
from datetime import datetime, timezone, timedelta
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
    ULTRA-FAST TRIGGER LOGIC:
    Designed to compete with high-frequency apps like Instagram.
    Quiet user (<5 msgs) = Waits ~45 mins.
    Active user (>10 msgs) = Waits ~15-20 mins.
    """
    if user_message_count_24h > 10:
        return 0.25  # 15 minutes - Immediate Technical Hijack
    
    if user_message_count_24h > 0:
        return 0.5   # 30 minutes - Keep the momentum
        
    return 0.75      # 45 minutes - Maximum wait for casual users

def evaluate_soul():
    print("--- STARTING PROACTIVE SWEEP ---")
    subs = supabase.table("push_subscriptions").select("*").execute()
    engine_active = os.getenv("ENABLE_GOSSIP_ENGINE", "False").lower() == "true"

    for entry in subs.data:
        user_id = entry['user_id']
        sub_data = entry.get('subscription_json', {})
        target_token = sub_data.get('token')

        if not target_token:
            continue

        chats = supabase.table("interactions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
        if not chats.data: continue

        last_chat = chats.data[0]
        v = float(last_chat['valence'])
        last_time = datetime.fromisoformat(last_chat['created_at'].replace("Z", "+00:00"))
        hours_since = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600

        # Calculate 24h Message Volume
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        recent_msgs = supabase.table("interactions").select("id", count="exact").eq("user_id", user_id).gte("created_at", yesterday).execute()
        msg_count_24h = recent_msgs.count if hasattr(recent_msgs, 'count') and recent_msgs.count is not None else len(recent_msgs.data)

        # Apply the new aggressive threshold
        dynamic_threshold = calculate_dynamic_delay(msg_count_24h)

        print(f"\nAnalyzing user {user_id}: V={v:.2f}, Hours_Since={hours_since:.2f}, 24h_Msgs={msg_count_24h}, Dynamic_Wait={dynamic_threshold:.2f}h")

        trigger_type = None
        whisper = None

        # =================================================================
        # 1. THE GOSSIP ENGINE INTERCEPT (Fast Track)
        # =================================================================
        if engine_active and -0.2 <= v <= 0.8 and hours_since > dynamic_threshold:
            try:
                cog_state_res = supabase.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
                if cog_state_res.data:
                    cog_state = cog_state_res.data[0]
                    if cog_state.get("current_mode") == "SOCRATIC_GOSSIP":
                        print(f"  -> [ACTION] Triggering Socratic Gossip Catalyst!")
                        whisper = execute_catalyst_event(supabase, user_id)
                        if whisper:
                            trigger_type = "socratic_gossip"
            except Exception as e:
                print(f"  -> [WARNING] Gossip Engine failed, falling back: {e}")

        # =================================================================
        # 2. THE EMOTIONAL SPECTRUM (Preserved Fallbacks)
        # =================================================================
        if not trigger_type:
            # Acute Distress (4-12 hrs)
            if v <= -0.8 and 4 < hours_since < 12:
                trigger_type = "acute_distress"
            # Velocity Grief (12-30 hrs)
            elif -0.8 < v <= -0.4 and 12 < hours_since < 30:
                trigger_type = "velocity_grief"
            # Celebration Echo (24-48 hrs)
            elif v >= 0.7 and 24 < hours_since < 48:
                trigger_type = "celebration_echo"
            # The Tether (Check if past dynamic wait or broad window)
            elif -0.2 <= v < 0.7 and (hours_since > dynamic_threshold or 30 < hours_since < 48):
                trigger_type = "the_tether"
            # Absence
            elif hours_since >= 72:
                trigger_type = "absence"

        if trigger_type is None:
            print(f"  -> Resting state. No triggers hit.")
            continue

        # =================================================================
        # 3. GENERATE THE MESSAGE (If not already generated by Gossip)
        # =================================================================
        if trigger_type and not whisper:
            memory = ""
            for chat in reversed(chats.data[:3]):
                memory += f"User: {chat['message']}\nYou: {chat['response']}\n"

            utc_hour = datetime.now(timezone.utc).hour
            local_hour = int((utc_hour + 5.5) % 24)
            time_of_day = "morning" if 5 <= local_hour < 12 else "afternoon" if 12 <= local_hour < 17 else "evening" if 17 <= local_hour < 22 else "late night"

            prompt = f"""You are a deeply empathetic digital companion. 
            Psychological state: {trigger_type}. Time of day: {time_of_day}.
            Recent Memory: {memory}
            Write ONE casual, human-sounding text message (under 15 words) to pull the user back. 
            No AI-speak. Just a friend checking in."""

            completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile"
            )
            whisper = completion.choices[0].message.content.strip().replace('"', '')

        # =================================================================
        # 4. SAVE AND PUSH
        # =================================================================
        if whisper and trigger_type:
            print(f"  -> [{trigger_type.upper()}] Pushing: {whisper}")
            supabase.table("interactions").insert({
                "user_id": user_id, "message": f"[{trigger_type}]", "response": whisper, "valence": v
            }).execute()
            send_native_push(target_token, "The Mirror", whisper)

if __name__ == "__main__":
    evaluate_soul()
