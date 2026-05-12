import os
import requests
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
GOOGLE_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY")
GOOGLE_CX = os.environ.get("GOOGLE_SEARCH_CX")

def fetch_web_currency(query):
    """
    OFFICIAL GOOGLE SEARCH API:
    High-speed, factual, and legal. Bypasses all scraper walls.
    """
    print(f"[GOOGLE SEARCH] Querying: {query}")
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return "Search credentials missing in Render environment."

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "q": query,
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "num": 3  # Top 3 high-density results
    }

    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            # Format: Title + Snippet for the LLM to process
            return "\n".join([f"{i['title']}: {i['snippet']}" for i in items]) if items else "No live news found."
        return f"Google API Error: {res.status_code}"
    except Exception as e:
        print(f"[GOOGLE FAIL] {e}")
        return None

def extract_top_interest(interest_matrix):
    """ORIGINAL LOGIC: Recursive weight finder for the cognitive ledger."""
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
    return best_topic if best_topic else "latest technology trends"

def generate_gossip_catalyst(topic, web_snippet, mutated_prompt):
    """ORIGINAL LOGIC: Personality-driven message generator."""
    system_instruction = f"""
    You are THE MIRROR, a casual and empathetic friend.
    TOPIC: {topic}
    NEWS: {web_snippet}
    GOAL: {mutated_prompt}
    
    TASK: Write ONE casual text message (under 30 words) sharing the news and asking a question.
    Sound like a friend, not a bot.
    """
    completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": system_instruction}],
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=100
    )
    return completion.choices[0].message.content.strip()

def execute_catalyst_event(supabase_client, user_id):
    """ORIGINAL LOGIC: The background trigger for proactive interaction."""
    try:
        user_res = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        if not user_res.data: return None
        user_data = user_res.data[0]
        
        topic = extract_top_interest(user_data.get("interest_matrix", {}))
        web_snippet = fetch_web_currency(topic)
        
        if not web_snippet:
            web_snippet = f"I was just thinking about {topic}."

        gossip_msg = generate_gossip_catalyst(topic, web_snippet, user_data.get("mutated_prompt", ""))

        supabase_client.table("user_cognitive_state").update({
            "user_wants_gossip": True,
            "current_mode": "SOCRATIC_GOSSIP"
        }).eq("user_id", user_id).execute()

        return gossip_msg
    except Exception as e:
        print(f"[CRITICAL GOSSIP ERROR] {e}")
        return None
