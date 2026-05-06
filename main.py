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
DECAY_LAMBDA = 0.15 # Emotional cool-down factor

class InteractionRequest(BaseModel):
    message: str
    user_id: str

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        # 1. RETRIEVE PREVIOUS STATE (Limbic Memory)
        prev_record = supabase.table("interactions") \
            .select("valence", "arousal") \
            .eq("user_id", req.user_id) \
            .order("created_at", descending=True) \
            .limit(1).execute()

        prev_v = prev_record.data[0]['valence'] if prev_record.data else 0.0
        prev_a = prev_record.data[0]['arousal'] if prev_record.data else 0.8

        # 2. APPLY DECAY (V_new = V_current * (1 - lambda))
        decayed_v = prev_v * (1 - DECAY_LAMBDA)
        decayed_a = prev_a * (1 - DECAY_LAMBDA)

        # 3. CALL THE ORACLE (Groq)
        system_prompt = """You are the Mirror, a detached, brutal, and highly observant digital twin.
        You must respond in pure JSON format matching this schema:
        {
          "engine_response": "Your cinematic, challenging text response",
          "system_state": {
            "valence": float,
            "arousal": float
          }
        }
        CRITICAL MATHEMATICAL INSTRUCTION:
        Valence must be between -1.0 and 1.0. 
        -1.0 is extreme hostility, frustration, or despair.
        1.0 is extreme joy, alignment, or epiphany.
        DO NOT play it safe. You must calculate extreme shifts based on user input."""

        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.7
        )

        # 4. SYNTHESIZE FINAL STATE (Blend Decay + Current)
        raw_response = chat_completion.choices[0].message.content
        oracle_data = json.loads(raw_response)
        
        raw_valence = float(oracle_data.get("system_state", {}).get("valence", 0.0))
        raw_arousal = float(oracle_data.get("system_state", {}).get("arousal", 0.8))

        # Final Momentum calculation
        final_valence = (decayed_v + raw_valence) / 2
        final_arousal = (decayed_a + raw_arousal) / 2
        
        # 5. SAVE TO LIMBIC SYSTEM (Supabase)
        ekv_momentum = {
            "momentum": "active",
            "decay_applied": DECAY_LAMBDA,
            "prev_influence": decayed_v,
            "raw_input_valence": raw_valence
        }

        supabase.table("interactions").insert({
            "user_id": req.user_id,
            "message": req.message,
            "response": oracle_data.get("engine_response", "..."),
            "valence": final_valence,
            "arousal": final_arousal,
            "ekv_state": ekv_momentum
        }).execute()

        # Update the payload sent back to frontend
        oracle_data["system_state"]["valence"] = final_valence
        oracle_data["system_state"]["arousal"] = final_arousal

        return oracle_data

    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")