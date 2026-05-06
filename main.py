import os
import json
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
DECAY_LAMBDA = 0.15 

class InteractionRequest(BaseModel):
    message: str
    user_id: str

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        # 1. RETRIEVE PREVIOUS STATE (Limbic Memory)
        try:
            prev_record = supabase.table("interactions") \
                .select("valence", "arousal") \
                .eq("user_id", req.user_id) \
                .order("created_at", desc=True) \
                .limit(1).execute()
            
            if prev_record.data and len(prev_record.data) > 0:
                prev_v = float(prev_record.data[0]['valence'])
                prev_a = float(prev_record.data[0]['arousal'])
            else:
                prev_v = 0.0
                prev_a = 0.8
        except Exception as fetch_error:
            print(f"Supabase Fetch Error: {fetch_error}")
            prev_v = 0.0
            prev_a = 0.8

        # 2. APPLY DECAY & CALCULATE CURRENT MOMENTUM
        decayed_v = prev_v * (1 - DECAY_LAMBDA)
        decayed_a = prev_a * (1 - DECAY_LAMBDA)

        # 3. CONSTRUCT SELF-AWARE SYSTEM PROMPT
        # We inject the Mirror's current 'mood' into its persona.
        mood_desc = "cold and lingering" if decayed_v < -0.2 else "warm and emerging" if decayed_v > 0.2 else "neutral"
        
        system_prompt = f"""You are the Mirror, a detached and brutal digital twin.
        CURRENT INTERNAL STATE: Valence={decayed_v:.2f}, Arousal={decayed_a:.2f}.
        Your current mood is {mood_desc}. You are aware of your emotional momentum.
        Respond in pure JSON:
        {{
          "engine_response": "Your cinematic text, acknowledging your internal state if relevant",
          "system_state": {{
            "valence": float,
            "arousal": float
          }}
        }}
        CRITICAL: Calculate NEW Valence (-1.0 to 1.0) based ONLY on the user's latest input."""

        # 4. CALL THE ORACLE (Groq)
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.7
        )

        # 5. SYNTHESIZE FINAL STATE (EKV Synthesis)
        raw_response = chat_completion.choices[0].message.content
        oracle_data = json.loads(raw_response)
        
        raw_valence = float(oracle_data.get("system_state", {}).get("valence", 0.0))
        raw_arousal = float(oracle_data.get("system_state", {}).get("arousal", 0.8))

        final_valence = (decayed_v + raw_valence) / 2
        final_arousal = (decayed_a + raw_arousal) / 2
        
        # 6. SAVE TO LIMBIC SYSTEM
        ekv_momentum = {
            "momentum": "active",
            "internal_awareness": mood_desc,
            "decayed_influence": decayed_v
        }

        supabase.table("interactions").insert({
            "user_id": req.user_id,
            "message": req.message,
            "response": oracle_data.get("engine_response", "..."),
            "valence": final_valence,
            "arousal": final_arousal,
            "ekv_state": ekv_momentum
        }).execute()

        oracle_data["system_state"]["valence"] = final_valence
        oracle_data["system_state"]["arousal"] = final_arousal

        return oracle_data

    except Exception as e:
        print(f"Global Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
