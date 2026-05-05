import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq

app = FastAPI()

# Enable unrestricted CORS for development bridge
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

class UserMessage(BaseModel):
    user_id: str
    message: str

@app.post("/api/interact")
async def process_interaction(payload: UserMessage):
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are the Mirror. Be observant, detached, and challenging."},
                {"role": "user", "content": payload.message}
            ],
            model="llama-3.1-8b-instant",
        )
        return {
            "engine_response": chat_completion.choices[0].message.content,
            "system_state": {"current_valence": -0.5, "current_arousal": 0.8},
            "ui_directives": {"background_hex": "#1A0505"}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
