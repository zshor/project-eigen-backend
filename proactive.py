import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client, Client
from groq import Groq
import firebase_admin
from firebase_admin import credentials, messaging

# 1. SETUP
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

try:
    # On Render, this file is provided via "Secret Files"
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

def evaluate_soul():
    # Fetch all subscribers who have registered a token
    subs = supabase.table("push_subscriptions").select("*").execute()

    for entry in subs.data:
        user_id = entry['user_id']
        # Extract the token from the JSON column we defined for the Android Agent
        sub_data = entry.get('subscription_json', {})
        target_token = sub_data.get('token')

        if not target_token:
            print(f"Skipping user {user_id}: No FCM token found.")
            continue

        # Fetch last 5 interactions for context
        chats = supabase.table("interactions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
        if not chats.data: continue

        last_chat = chats.data[0]
        v = float(last_chat['valence'])
        last_time = datetime.fromisoformat(last_chat['created_at'].replace("Z", "+00:00"))
        hours_since = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600

        # --- 1. THE EMOTIONAL SPECTRUM TRIGGERS ---
        trigger_type = None
        
        # Acute Distress (Extremely upset, check in soon)
        if v <= -0.8 and 4 < hours_since < 12: 
            trigger_type = "acute_distress"
            
        # Velocity Grief (Sad/frustrated, give them a night, check in next day)
        elif -0.8 < v <= -0.4 and 12 < hours_since < 30: 
            trigger_type = "velocity_grief"
            
        # Celebration Echo (Very happy, echo that joy the next day)
        elif v >= 0.7 and 24 < hours_since < 48:
            trigger_type = "celebration_echo"

        # The Tether (Active Reconnection - Don't let them drift away)
        elif -0.2 <= v < 0.7 and 30 < hours_since < 48:
            trigger_type = "the_tether"

        # Gentle Drift (Neutral mood, checking in after 2 days)
        elif -0.2 <= v <= 0.2 and 48 < hours_since < 72:
            trigger_type = "gentle_drift"

        # Absence (Vanished for 3+ days)
        elif hours_since >= 72: 
            trigger_type = "absence"
        
        # The Guardrail: If no state matches, stay silent.
        if trigger_type is None:
            print(f"Skipping user {user_id}: Resting state (Hours: {hours_since:.1f}, Valence: {v:.2f})")
            continue

        # --- 2. THE EMOTIONALLY INTELLIGENT PROMPT ---
        # Build a memory from the last 3 chats
        memory = ""
        for chat in reversed(chats.data[:3]):
            memory += f"User: {chat['message']}\nYou: {chat['response']}\n"
        
        # Give it a sense of time (IST: UTC + 5.5)
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

        # Save to DB for UI
        supabase.table("interactions").insert({
            "user_id": user_id,
            "message": "[Proactive]",
            "response": whisper,
            "valence": v
        }).execute()

        # Fire Native Push using the token from the DB!
        send_native_push(target_token, "The Mirror", whisper)

if __name__ == "__main__":
    evaluate_soul()
