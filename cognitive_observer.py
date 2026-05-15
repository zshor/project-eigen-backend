import os
import json
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def update_cognitive_ledger(supabase_client, user_id, recent_chat_history):
    """
    Background worker: Analyzes chat to update the interest matrix and mutate the next gossip prompt.
    Uses the 'Firewall' update pattern to protect the manual UI toggle.
    """
    try:
        # 1. Fetch current state and toggle status
        state_response = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        state_data = state_response.data[0] if state_response.data else {}
        current_matrix = state_data.get("interest_matrix", {})
        manual_on = state_data.get("manual_gossip_toggle", False)

        # OPTIMIZATION: Safe truncation of the JSON matrix to prevent token explosions
        safe_matrix_str = json.dumps(current_matrix)[:1500]

        # 2. The Multi-Domain System Prompt (Full Logic Restoration)
        system_instruction = f"""
        You are an autonomous profiling algorithm mapping the user's mind into a Multi-Domain JSON Tree.
        
        MANUAL RESEARCH MODE: {"ACTIVE" if manual_on else "INACTIVE"}
        
        CURRENT INTEREST MATRIX:
        {safe_matrix_str}
        
        RECENT CHAT:
        "{recent_chat_history}"
        
        THE MULTI-DOMAIN PROTOCOL:
        1. Root domains can be anything (e.g., 'fashion', 'tech', 'cricket', 'philosophy').
        2. MAXIMUM DEPTH IS 4 LEVELS. L1 (Macro) -> L2 -> L3 -> L4 (Specific Entity).
        3. Update weights of mentioned topics. Add new nodes if a new topic appears.
        
        PROMPT MUTATION RULE:
        Write a `mutated_prompt` for the Gossip Engine. 
        - If Manual Research is ACTIVE, prioritize drilling down into the specific entities just discussed in the web results.
        - If Manual Research is INACTIVE:
            a) If there is a SHALLOW branch (L1 or L2), write a prompt to DRILL DOWN into it.
            b) If there is a MAXED OUT branch (L4), write a prompt to GOSSIP about it using web search.
        - ROTATE TOPICS. Do not repeat what was just discussed.
        
        VIBE CHECK:
        Set `user_wants_gossip` to true ONLY IF the user explicitly asks for news or seems bored.

        CRITICAL - YOU MUST RESPOND ONLY IN THIS EXACT JSON FORMAT:
        {{
            "updated_matrix": {{...}},
            "mutated_prompt": "Your proactive gossip prompt string goes here",
            "user_wants_gossip": true or false
        }}
        """
        
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_instruction}],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"} 
        )
        
        ai_data = json.loads(completion.choices[0].message.content)
        
        # 3. THE HANDSHAKE PROTECTION
        # If manual_on is True, we force user_wants_gossip to stay True so the UI stays Orange.
        final_gossip_intent = True if manual_on else ai_data.get("user_wants_gossip", False)

        # 4. SECURE UPDATE (The Firewall)
        # Target ONLY brain columns to avoid overwriting manual_gossip_toggle.
        supabase_client.table("user_cognitive_state").update({
            "interest_matrix": ai_data.get("updated_matrix", current_matrix),
            "mutated_prompt": ai_data.get("mutated_prompt", ""),
            "user_wants_gossip": final_gossip_intent
        }).eq("user_id", user_id).execute()
        
        print(f"[OBSERVER] Brain synchronized. Research Mode: {manual_on}")
        
    except Exception as e:
        print(f"[OBSERVER ERROR] {e}")
