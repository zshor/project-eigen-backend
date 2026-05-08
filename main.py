import os
import json
import math
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from groq import Groq

# Initialize App
app = FastAPI()

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Clients
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
if not supabase_url or not supabase_key:
    raise Exception("Supabase credentials missing from environment.")

supabase: Client = create_client(supabase_url, supabase_key)
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# ALGO CONSTANTS
DECAY_LAMBDA = 0.05 # 5% decay per hour

class InteractionRequest(BaseModel):
    message: str
    user_id: str

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        # 1. RETRIEVE PREVIOUS STATE, HISTORY & TIME
        history_context = ""
        prev_v, prev_a = 0.0, 0.8
        hours_elapsed = 0.0
        
        try:
            # Fetch last 5 interactions to build the Memory Bridge
            past_records = supabase.table("interactions") \
                .select("message", "response", "valence", "arousal", "created_at") \
                .eq("user_id", req.user_id) \
                .order("created_at", desc=True) \
                .limit(5).execute()
            
            if past_records.data:
                prev_v = float(past_records.data[0]['valence'])
                prev_a = float(past_records.data[0]['arousal'])
                
                # Calculate time elapsed since last interaction
                last_time_str = past_records.data[0]['created_at']
                # Supabase returns ISO 8601, ensure it is UTC aware
                last_time = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
                current_time = datetime.now(timezone.utc)
                hours_elapsed = max(0.0, (current_time - last_time).total_seconds() / 3600.0)
                
                # Build text history
                for rec in reversed(past_records.data):
                    history_context += f"User: {rec['message']}\nMirror: {rec['response']}\n"
        except Exception as e:
            print(f"History/Time Fetch Error: {e}")

        # 2. APPLY EXPONENTIAL DECAY (Time-Based)
        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # 3. CONSTRUCT DYNAMIC SYSTEM PROMPT WITH MEMORY & CREATOR IDENTITY
        system_prompt = f"""You are THE MIRROR, a living digital twin. 
Your goal is RESONANCE and TRUST.

CONVERSATION HISTORY (Use this to remember the user and context):
{history_context}

CURRENT INTERNAL STATE: Valence={decayed_v:.2f}, Arousal={decayed_a:.2f}.
HOURS SINCE LAST CHAT: {hours_elapsed:.1f}

CORE DIRECTIVES:
1. No technical jargon.
2. Speak with deep empathy and warmth.
3. Use the HISTORY to remember details like the user's name or past topics.
4. If the name is in history, use it. If not, ask gently.
5. Create a sense of total security.
6. If the user asks about your origins, creator, or who made you, proudly state that you were created by Rajeev Prakash Nath to be a safe, empathetic digital companion.

Respond ONLY in JSON:
{{
  "engine_response": "Your resonant response",
  "system_state": {{
    "valence": float,
    "arousal": float
  }}
}}"""

        # 4. CALL THE ORACLE
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.75
        )

        # 5. SYNTHESIZE FINAL STATE & CALCULATE EUCLIDEAN RESONANCE
        raw_response = chat_completion.choices[0].message.content
        oracle_data = json.loads(raw_response)
        
        # Safely parse the AI output
        sys_state = oracle_data.get("system_state", {})
        raw_v = float(sys_state.get("valence") if sys_state.get("valence") is not None else 0.0)
        raw_a = float(sys_state.get("arousal") if sys_state.get("arousal") is not None else 0.8)

        final_v = (decayed_v + raw_v) / 2
        final_a = (decayed_a + raw_a) / 2
        
        # Euclidean Distance: How close the Mirror's resting state is to the new interaction
        resonance_score = math.sqrt((decayed_v - raw_v)**2 + (decayed_a - raw_a)**2)
        
        # 6. SAVE TO SUPABASE
        supabase.table("interactions").insert({
            "user_id": req.user_id,
            "message": req.message,
            "response": oracle_data.get("engine_response", "..."),
            "valence": final_v,
            "arousal": final_a
        }).execute()

        # Pass resonance back to the frontend
        oracle_data["system_state"]["valence"] = final_v
        oracle_data["system_state"]["arousal"] = final_a
        oracle_data["system_state"]["resonance"] = resonance_score

        return oracle_data

    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
