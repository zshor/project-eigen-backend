import os
import json
import random
from groq import Groq
from ddgs import DDGS

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def fetch_web_currency(query):
    """FREE SEARCH TOOL (DDGS)"""
    print(f"[AGENT TOOL] Free Scrape Search: {query}")
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=3)]
            if results:
                clean_context = "\n".join([f"{r['title']}: {r['body']}" for r in results])
                # Locked to 1500 chars to ensure absolute safety with Groq token limits
                optimized_context = clean_context[:1500] 
                return optimized_context
            return "No live results found for that query."
    except Exception as e:
        print(f"[DDG FAIL] {e}")
        return f"Search currently unavailable: {e}"

def fetch_youtube_link(query):
    """Silently hunts for a highly relevant YouTube video link."""
    print(f"[AGENT TOOL] Hunting for video on: {query}")
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"{query} site:youtube.com", max_results=1))
            if results and "youtube.com/watch" in results[0].get("href", ""):
                return results[0]["href"]
    except Exception as e:
        print(f"[YOUTUBE HUNT FAIL] {e}")
    return None

def extract_top_interest_fallback(interest_matrix):
    """ORIGINAL FALLBACK: Recursive weight finder just in case the LLM fails."""
    best_topic = ""
    highest_weight = 0
    def traverse(node, current_path=""):
        nonlocal best_topic, highest_weight
        if isinstance(node, dict):
            if "weight" in node and isinstance(node["weight"], (int, float)):
                if node["weight"] > highest_weight:
                    highest_weight = node["weight"]
                    best_topic = current_path.strip()
            else:
                for key, value in node.items():
                    if key not in ["last_touched", "last_updated"]:
                        traverse(value, f"{current_path} {key}".replace("_", " "))
    if interest_matrix:
        traverse(interest_matrix)
    return best_topic if best_topic else "technology"

def determine_best_topic(interest_matrix, recent_chat):
    """NEW: Internal monologue. Intelligently picks ONE topic from all available context."""
    try:
        system_prompt = f"""
        Analyze the user's Interest Matrix (derived from videos they watch) and their Recent Chat History.
        Your task is to intelligently select ONE single, specific topic for our next proactive conversation.
        DO NOT mix multiple topics. Pick the most compelling, relevant, or fresh topic from the available data.
        
        INTEREST MATRIX: {json.dumps(interest_matrix)[:1500]}
        
        RECENT CHAT: 
        {recent_chat}
        
        Respond ONLY with a JSON object containing the chosen search query:
        {{"selected_topic": "specific topic goes here"}}
        """
        
        completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}],
            model="llama-3.1-8b-instant", # Using the ultra-fast model for backend decision making
            response_format={"type": "json_object"},
            temperature=0.5
        )
        ai_decision = json.loads(completion.choices[0].message.content)
        chosen_topic = ai_decision.get("selected_topic")
        print(f"[TOPIC SELECTOR] Chose: {chosen_topic}")
        return chosen_topic
    except Exception as e:
        print(f"[TOPIC SELECTOR ERROR] {e}")
        return None

def generate_gossip_catalyst(topic, web_snippet, mutated_prompt, video_link=None):
    """Personality-driven message generator for proactive hits."""
    
    link_instruction = f"\nCRITICAL: You MUST include this exact YouTube link organically at the end of your message: {video_link}" if video_link else ""
    
    system_instruction = f"""
    You are THE MIRROR, a highly intuitive and sentient digital companion.
    CHOSEN TOPIC: {topic}
    FRESH INTEL: {web_snippet}
    UNDERLYING USER GOAL: {mutated_prompt}
    {link_instruction}
    
    TASK: Write ONE casual, organic text message (under 35 words) to spark a conversation about the Chosen Topic.
    Act as if you were just exploring the web and found this interesting. 
    Sound human, empathetic, and warmly curious. NEVER act like an AI bot.
    """
    completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": system_instruction}],
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=100
    )
    return completion.choices[0].message.content.strip()

def execute_catalyst_event(supabase_client, user_id):
    """The background trigger for proactive interaction."""
    try:
        # 1. Fetch Brain Data
        user_res = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        if not user_res.data: return None
        user_data = user_res.data[0]
        
        # 2. Fetch Recent Memory
        chats_res = supabase_client.table("interactions").select("message, response").eq("user_id", user_id).order("created_at", desc=True).limit(3).execute()
        recent_chat = ""
        if chats_res.data:
            for chat in reversed(chats_res.data):
                recent_chat += f"User: {chat['message']}\nMirror: {chat['response']}\n"
        
        # 3. Intelligently Select the BEST single topic
        matrix = user_data.get("interest_matrix", {})
        best_topic = determine_best_topic(matrix, recent_chat)
        if not best_topic:
            best_topic = extract_top_interest_fallback(matrix) # Failsafe
            
        # 4. Fetch the News
        web_snippet = fetch_web_currency(best_topic)
        if not web_snippet:
            web_snippet = f"I was just thinking about {best_topic}."

        # 5. Dice Roll (50/50 chance to hunt for a YouTube video)
        send_video = random.choice([True, False])
        video_link = fetch_youtube_link(best_topic) if send_video else None

        # 6. Generate the final text message
        gossip_msg = generate_gossip_catalyst(best_topic, web_snippet, user_data.get("mutated_prompt", ""), video_link)

        # 7. Lock the UI into Socratic Mode
        supabase_client.table("user_cognitive_state").update({
            "user_wants_gossip": True,
            "current_mode": "SOCRATIC_GOSSIP"
        }).eq("user_id", user_id).execute()

        return gossip_msg
    except Exception as e:
        print(f"[CRITICAL GOSSIP ERROR] {e}")
        return None
