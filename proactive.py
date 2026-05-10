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

        # --- UPDATED STRICT TRIGGER LOGIC ---
        trigger_type = None
        
        if v < -0.4 and 12 < hours_since < 30: 
            trigger_type = "velocity_grief"
        elif hours_since > 72: 
            trigger_type = "absence"
        
        # If no conditions are met, SKIP this user and DO NOT send a message.
        # This protects your Groq API limits and prevents spamming the user.
        if trigger_type is None:
            print(f"Skipping user {user_id}: No trigger met (Hours: {hours_since:.1f}, Valence: {v:.2f})")
            continue
        # ------------------------------------

        prompt = f"You are THE MIRROR. One short, deep sentence for user. Trigger: {trigger_type}. History: {last_chat['message']}"

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
