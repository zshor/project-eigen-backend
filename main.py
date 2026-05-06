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

class InteractionRequest(BaseModel):
    message: str
    user_id: str

@app.post("/api/interact")
async def interact(req: InteractionRequest):
    try:
        # 1. The System Prompt (Updated with strict emotional bounds)
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
        DO NOT play it safe. DO NOT default to 0.0 or 0.1. You must calculate extreme shifts based on the emotional intensity of the user's input."""

        # 2. Call the Oracle (Groq)
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"},
            temperature=0.7
        )

        # 3. Parse the Response
        raw_response = chat_completion.choices[0].message.content
        oracle_data = json.loads(raw_response)
        
        valence = float(oracle_data.get("system_state", {}).get("valence", 0.0))
        arousal = float(oracle_data.get("system_state", {}).get("arousal", 0.8))
        engine_response = oracle_data.get("engine_response", "...")

        # 4. Save to the Limbic System (Supabase)
        supabase.table("interactions").insert({
            "user_id": req.user_id,
            "message": req.message,
            "response": engine_response,
            "valence": valence,
            "arousal": arousal,
            "ekv_state": {"momentum": "calculating"}
        }).execute()

        # 5. Return to Frontend
        return oracle_data

    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")