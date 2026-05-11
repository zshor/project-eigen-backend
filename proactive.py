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
        cred = credentials.Certificate("firebase-admin-key.json")
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

# --- THE DYNAMIC ALGORITHM ---
def calculate_dynamic_delay(user_message_count_24h):
    """ Quiet user = Waits ~1.5 hrs. Chatty user = Waits up to 9.5 hrs. """
    base_wait_hours = 1.5 
    engagement_multiplier = min(user_message_count_24h / 4, 8) 
    return base_wait_hours + engagement_multiplier

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
        
        dynamic_threshold = calculate_dynamic_delay(msg_count_24h)

        print(f"\nAnalyzing user {user_id}: V={v:.2f}, Hours={hours_since:.1f}, 24h_Msgs={msg_count_24h}, Dynamic_Wait={dynamic_threshold:.1f}h")

        trigger_type = None
        whisper = None

        # =================================================================
        # 1. THE GOSSIP ENGINE INTERCEPT (Fast Track)
        # =================================================================
        if engine_active and -0.2 <= v <= 0.8 and hours_since > dynamic_threshold:
            try:
                cog_state = supabase.table("user_cognitive_state").select("*").eq("user_id", user_id).execute().data
                if cog_state and cog_state[0].get("current_mode") == "SOCRATIC_GOSSIP":
                    print(f"  -> [ACTION] Triggering Socratic Gossip Catalyst!")
                    whisper = execute_catalyst_event(supabase, user_id)
                    if whisper:
                        trigger_type = "socratic_gossip"
            except Exception as e:
                print(f"  -> [WARNING] Gossip Engine failed, falling back: {e}")

        # =================================================================
        # 2. THE EMOTIONAL SPECTRUM (Standard Fallbacks)
        # =================================================================
        if not trigger_type:
            # Acute Distress
            if v <= -0.8 and 4 < hours_since < 12:
                trigger_type = "acute_distress"
            # Velocity Grief
            elif -0.8 < v <= -0.4 and 12 < hours_since < 30:
                trigger_type = "velocity_grief"
            # Celebration Echo
            elif v >= 0.7 and 24 < hours_since < 48:
                trigger_type = "celebration_echo"
            # The Tether 
            elif -0.2 <= v < 0.7 and 30 < hours_since < 48:
                trigger_type = "the_tether"
            # Gentle Drift
            elif -0.2 <= v <= 0.2 and 48 < hours_since < 72:
                trigger_type = "gentle_drift"
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

            prompt = f"""You are a deeply empathetic, emotionally intelligent companion. You are initiating a text message to pull the user back into conversation.
            Current time for the user: {time_of_day}.
            Psychological state: {trigger_type}.

            Recent Memory:
            {memory}

            Write ONE short, casual text message (under 15 words) to send as a push notification.
            CRITICAL: DO NOT act mystical. DO NOT mention gazing or reflections.
            Speak like a caring human friend texting them. Reference the time of day, ask if they've eaten, or ask a simple question about their last message to make them want to reply."""

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
            # Save to DB for UI
            supabase.table("interactions").insert({
                "user_id": user_id,
                "message": f"[{trigger_type}]",
                "response": whisper,
                "valence": v
            }).execute()

            # Fire Native Push
            send_native_push(target_token, "The Mirror", whisper)

if __name__ == "__main__":
    evaluate_soul()
