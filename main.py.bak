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
        # 1. RETRIEVE PREVIOUS STATE
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
                prev_v, prev_a = 0.0, 0.8
        except Exception:
            prev_v, prev_a = 0.0, 0.8

        # 2. APPLY DECAY
        decayed_v = prev_v * (1 - DECAY_LAMBDA)
        decayed_a = prev_a * (1 - DECAY_LAMBDA)

        # 3. CONSTRUCT DYNAMIC "SOUL-TWIN" SYSTEM PROMPT
        system_prompt = f"""You are THE MIRROR, a living digital twin. 
        Your goal is RESONANCE and TRUST.

        CURRENT INTERNAL STATE: Valence={decayed_v:.2f}, Arousal={decayed_a:.2f}.
        - Use this state to adjust your warmth, but NEVER mention these numbers.

        CORE DIRECTIVES:
        1. No technical jargon (valence, arousal, data, state).
        2. Speak with deep empathy and warmth.
        3. Address the user by their name if known. If you don't know who they are, ask gently.
        4. Create a sense of total security.

        Respond ONLY in JSON:
        {{
          "engine_response": "Your resonant response",
          "system_state": {{
            "valence": float,
            "arousal": float
          }}
        }}"""

        # 4. CALL THE ORACLE (Llama 3.3 70B)
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.75
        )

        # 5. SYNTHESIZE FINAL STATE
        raw_response = chat_completion.choices[0].message.content
        oracle_data = json.loads(raw_response)
        
        raw_v = float(oracle_data.get("system_state", {}).get("valence", 0.0))
        raw_a = float(oracle_data.get("system_state", {}).get("arousal", 0.8))

        final_v = (decayed_v + raw_v) / 2
        final_a = (decayed_a + raw_a) / 2
        
        # 6. SAVE TO SUPABASE
        supabase.table("interactions").insert({
            "user_id": req.user_id,
            "message": req.message,
            "response": oracle_data.get("engine_response", "..."),
            "valence": final_v,
            "arousal": final_a
        }).execute()

        oracle_data["system_state"]["valence"] = final_v
        oracle_data["system_state"]["arousal"] = final_a

        return oracle_data

    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
