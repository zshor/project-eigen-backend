import os
import json
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def update_cognitive_ledger(supabase_client, user_id, recent_chat_history):
    try:
        # 1. Fetch current state
        state_res = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        state_data = state_res.data[0] if state_res.data else {}
        current_matrix = state_data.get("interest_matrix", {})
        manual_on = state_data.get("manual_gossip_toggle", False)

        # 2. System Instruction
        system_instruction = f"""
        You are a profiling algorithm. 
        MODE: {"RESEARCH ACTIVE" if manual_on else "NORMAL"}
        MATRIX: {json.dumps(current_matrix)}
        CHAT: "{recent_chat_history}"
        
        TASK: Update the JSON interest matrix. 
        Set `user_wants_gossip` to true only if the user explicitly asks for news.
        """
        
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_instruction}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} 
        )
        
        ai_data = json.loads(completion.choices[0].message.content)
        
        # 3. PRESERVE THE TOGGLE STATE
        # If manual_on is True, we force user_wants_gossip to stay True
        final_gossip_intent = True if manual_on else ai_data.get("user_wants_gossip", False)

        supabase_client.table("user_cognitive_state").update({
            "interest_matrix": ai_data.get("updated_matrix", current_matrix),
            "mutated_prompt": ai_data.get("mutated_prompt", ""),
            "user_wants_gossip": final_gossip_intent
        }).eq("user_id", user_id).execute()
        
    except Exception as e:
        print(f"Observer failed: {e}")
