import os
import json
import math
from datetime import datetime, timezone
from supabase import create_client, Client
from pywebpush import webpush, WebPushException
from groq import Groq

# 1. SETUP
supabase: Client = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL")

def send_mirror_whisper(subscription, title, body):
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=PRIVATE_KEY,
            vapid_claims={"sub": CLAIM_EMAIL}
        )
        print(f"Whisper sent: {title}")
    except WebPushException as ex:
        print(f"Whisper failed: {ex}")

def evaluate_soul():
    subs = supabase.table("push_subscriptions").select("*").execute()
    
    for entry in subs.data:
        user_id = entry['user_id']
        sub_json = entry['subscription_json']
        
        chats = supabase.table("interactions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
        
        if not chats.data: continue
        
        last_chat = chats.data[0]
        v = float(last_chat['valence'])
        last_time = datetime.fromisoformat(last_chat['created_at'].replace("Z", "+00:00"))
        hours_since = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600

        trigger_type = None
        if v < -0.4 and 12 < hours_since < 24:
            trigger_type = "velocity_grief"
        elif hours_since > 72:
            trigger_type = "absence"
        elif v > 0.7 and 12 < hours_since < 24:
            trigger_type = "afterglow"
        elif 24 < hours_since < 48:
            trigger_type = "memory_bridge"
        else:
            trigger_type = "grounding"

        if trigger_type:
            context_string = "\n".join([f"User: {c['message']}\nMirror: {c['response']}" for c in reversed(chats.data)])
            prompt = f"You are THE MIRROR. Write a short, empathetic proactive notification (max 100 chars) for trigger: {trigger_type}. History: {context_string}"
            
            completion = groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile"
            )
            
            whisper = completion.choices[0].message.content.strip().replace('"', '')
            send_mirror_whisper(sub_json, "The Mirror", whisper)

if __name__ == "__main__":
    evaluate_soul()
