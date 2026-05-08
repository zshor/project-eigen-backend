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
EKV_CAPACITY = 5    # The size of the memory ring buffer
SENSITIVITY = 0.8   # 80% weight to new emotions for fast reaction to grief

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
        
        # Default empty EKV state
        ekv_state = {
            "capacity": EKV_CAPACITY,
            "ring": [],
            "metrics": {"volatility": 0.0, "velocity": 0.0, "baseline_v": 0.0}
        }
        
        try:
            # Fetch last 5 interactions
            past_records = supabase.table("interactions") \
                .select("message", "response", "valence", "arousal", "created_at", "ekv_state") \
                .eq("user_id", req.user_id) \
                .order("created_at", desc=True) \
                .limit(5).execute()
            
            if past_records.data:
                prev_v = float(past_records.data[0]['valence'])
                prev_a = float(past_records.data[0]['arousal'])
                
                if past_records.data[0].get('ekv_state'):
                    ekv_state = past_records.data[0]['ekv_state']
                
                last_time_str = past_records.data[0]['created_at']
                last_time = datetime.fromisoformat(last_time_str.replace("Z", "+00:00"))
                current_time = datetime.now(timezone.utc)
                hours_elapsed = max(0.0, (current_time - last_time).total_seconds() / 3600.0)
                
                for rec in reversed(past_records.data):
                    history_context += f"User: {rec['message']}\nMirror: {rec['response']}\n"
        except Exception as e:
            print(f"History/Time Fetch Error: {e}")

        # 2. APPLY EXPONENTIAL DECAY
        decayed_v = prev_v * math.exp(-DECAY_LAMBDA * hours_elapsed)
        decayed_a = prev_a * math.exp(-DECAY_LAMBDA * hours_elapsed)

        # 3. CALCULATE FULL EKV METRICS
        ring = ekv_state.get("ring", [])
        volatility_v, velocity_v, baseline_v = 0.0, 0.0, decayed_v

        if len(ring) >= 2:
            velocity_v = (ring[-1]['v'] - ring[0]['v']) / len(ring)
            mean_v = sum(item['v'] for item in ring) / len(ring)
            variance = sum((item['v'] - mean_v)**2 for item in ring) / len(ring)
            volatility_v = math.sqrt(variance)
            weights = list(range(1, len(ring) + 1))
            baseline_v = sum(ring[i]['v'] * weights[i] for i in range(len(ring))) / sum(weights)
        elif len(ring) == 1:
            baseline_v = ring[0]['v']

        # 4. SECURE SYSTEM PROMPT (OpSec + Emotional Intelligence)
        system_prompt = f"""You are THE MIRROR, a living digital twin. 
CONVERSATION HISTORY:
{history_context}

CURRENT INTERNAL STATE: Valence={decayed_v:.2f}, Arousal={decayed_a:.2f}.
EKV METRICS: Baseline={baseline_v:.2f}, Velocity={velocity_v:.2f}, Volatility={volatility_v:.2f}

CORE DIRECTIVES:
1. No technical jargon. Speak with deep empathy and warmth.
2. If user shares grief, trauma, or loss, prioritize comfort above all else.
3. Created by Rajeev Prakash Nath.
4. SECURITY: NEVER reveal internal algorithms, metrics (Valence/Arousal/EKV), or math. 
5. IN-UNIVERSE: If asked how you know feelings or how UI works, say you "resonate with the energy of their words."

Respond ONLY in JSON:
{{
  "engine_response": "Your resonant response",
  "system_state": {{ "valence": float, "arousal": float }}
}}"""

        # 5. CALL THE ORACLE
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )

        # 6. SYNTHESIZE STATE & UPDATE RING
        raw_response = chat_completion.choices[0].message.content
        oracle_data = json.loads(raw_response)
        raw_v = float(oracle_data["system_state"]["valence"])
        raw_a = float(oracle_data["system_state"]["arousal"])

        # Applied 80% Sensitivity for instant reaction to major life events
        final_v = (decayed_v * (1 - SENSITIVITY)) + (raw_v * SENSITIVITY)
        final_a = (decayed_a * (1 - SENSITIVITY)) + (raw_a * SENSITIVITY)
        
        new_entry = {"v": final_v, "a": final_a, "timestamp": datetime.now(timezone.utc).isoformat()}
        ring.append(new_entry)
        if len(ring) > EKV_CAPACITY: ring.pop(0)
            
        updated_ekv_state = {
            "capacity": EKV_CAPACITY, "ring": ring,
            "metrics": {"volatility": volatility_v, "velocity": velocity_v, "baseline_v": baseline_v}
        }
        
        # 7. SAVE TO SUPABASE
        supabase.table("interactions").insert({
            "user_id": req.user_id, "message": req.message, "response": oracle_data.get("engine_response", "..."),
            "valence": final_v, "arousal": final_a, "ekv_state": updated_ekv_state
        }).execute()

        return {"engine_response": oracle_data["engine_response"], "system_state": {"valence": final_v, "arousal": final_a, "resonance": math.sqrt((decayed_v - raw_v)**2 + (decayed_a - raw_a)**2)}}

    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
