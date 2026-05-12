import os
import json
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def update_cognitive_ledger(supabase_client, user_id, recent_chat_history):
    """Runs in the background to mutate the user's JSON brain without wiping the toggle."""
    try:
        # 1. Fetch current state and toggle status
        state_response = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        state_data = state_response.data[0] if state_response.data else {}
        current_matrix = state_data.get("interest_matrix", {})
        manual_on = state_data.get("manual_gossip_toggle", False)

        # 2. The Multi-Domain System Prompt (Preserving your original L1-L4 logic)
        system_instruction = f"""
        You are an autonomous profiling algorithm mapping the user's mind into a Multi-Domain JSON Tree.
        
        MANUAL RESEARCH MODE: {"ACTIVE" if manual_on else "INACTIVE"}
        
        CURRENT INTEREST MATRIX:
        {json.dumps(current_matrix)}
        
        RECENT CHAT:
        "{recent_chat_history}"
        
        THE MULTI-DOMAIN PROTOCOL:
        1. Root domains can be anything (e.g., 'fashion', 'tech', 'cricket').
        2. MAXIMUM DEPTH IS 4 LEVELS. L1 -> L2 -> L3 -> L4 (Specific Entity).
        3. Update weights of mentioned topics. Add new nodes if a new topic appears.
        
        PROMPT MUTATION RULE:
        Write a `mutated_prompt` for the Gossip Engine. 
        - If Manual Research is ACTIVE, prioritize drilling down into specific entities discussed in the web results.
        - ROTATE TOPICS. Do not repeat what was just discussed.
        
        VIBE CHECK:
        Set `user_wants_gossip` to true ONLY IF the user explicitly asks for news or seems bored.
        """
        
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_instruction}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} 
        )
        
        ai_data = json.loads(completion.choices[0].message.content)
        
        # 3. THE FIREWALL UPDATE
        # If manual_on is True, we force user_wants_gossip to stay True so the UI stays Orange.
        final_gossip_intent = True if manual_on else ai_data.get("user_wants_gossip", False)

        # We use .update() instead of .upsert() to target ONLY the brain columns.
        supabase_client.table("user_cognitive_state").update({
            "interest_matrix": ai_data.get("updated_matrix", current_matrix),
            "mutated_prompt": ai_data.get("mutated_prompt", ""),
            "user_wants_gossip": final_gossip_intent
        }).eq("user_id", user_id).execute()
        
        print(f"Cognitive Ledger updated (Manual Toggle Respected: {manual_on})")
        
    except Exception as e:
        print(f"Observer failed: {e}")
