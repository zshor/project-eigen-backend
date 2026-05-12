import os
import json
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def update_cognitive_ledger(supabase_client, user_id, recent_chat_history):
    """Runs in the background to mutate the user's JSON brain."""
    try:
        # 1. Fetch current state and toggle status
        state_response = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        state_data = state_response.data[0] if state_response.data else {}
        current_matrix = state_data.get("interest_matrix", {})
        manual_on = state_data.get("manual_gossip_toggle", False)

        # 2. The Multi-Domain System Prompt (Preserving all original logic)
        system_instruction = f"""
        You are an autonomous profiling algorithm mapping the user's mind into a Multi-Domain JSON Tree.
        
        MANUAL RESEARCH MODE: {"ACTIVE" if manual_on else "INACTIVE"}
        
        CURRENT INTEREST MATRIX:
        {json.dumps(current_matrix)}
        
        RECENT CHAT:
        "{recent_chat_history}"
        
        THE MULTI-DOMAIN PROTOCOL:
        1. The tree can have multiple Level 1 root domains (e.g., 'fashion', 'tech', 'politics').
        2. MAXIMUM DEPTH IS 4 LEVELS. L1 (Macro) -> L2 -> L3 -> L4 (Specific Entity).
        3. Update weights of mentioned topics. Add new nodes if a new topic appears.
        
        PROMPT MUTATION RULE:
        Write a `mutated_prompt` instructing the AI on what to talk about NEXT time. 
        - If there is a SHALLOW branch, write a prompt to DRILL DOWN into it.
        - If there is a MAXED OUT branch (Level 4), write a prompt to GOSSIP about it using web search.
        - ROTATE TOPICS. Do not write a prompt about a topic just discussed.
        - If Manual Research is ACTIVE, prioritize drilling down into the specific entities discussed.
        
        VIBE CHECK:
        Set `user_wants_gossip` to true ONLY IF the user explicitly asks for news, seems bored, or wants you to share info. Otherwise, false.
        
        TASK:
        Respond in this exact JSON schema:
        {{
          "updated_matrix": {{}},
          "mutated_prompt": "string",
          "user_wants_gossip": boolean
        }}
        """
        
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_instruction}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} 
        )
        
        ai_data = json.loads(completion.choices[0].message.content)
        
        # 3. SAFE UPDATE (Replacing UPSERT with UPDATE + EQ)
        # We target ONLY the matrix and prompts to prevent overwriting manual_gossip_toggle.
        supabase_client.table("user_cognitive_state").update({
            "interest_matrix": ai_data.get("updated_matrix", current_matrix),
            "mutated_prompt": ai_data.get("mutated_prompt", ""),
            "user_wants_gossip": ai_data.get("user_wants_gossip", False)
        }).eq("user_id", user_id).execute()
        
        print(f"Cognitive Ledger updated for {user_id}")
        
    except Exception as e:
        print(f"Observer failed silently: {e}")
