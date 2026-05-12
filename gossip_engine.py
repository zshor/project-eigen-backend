import os
import requests
from groq import Groq
from bs4 import BeautifulSoup

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def fetch_web_currency(query):
    """
    FREE BACKGROUND SCRAPER (DuckDuckGo):
    Used only by the proactive bot to save Groq API quota.
    """
    print(f"[SYSTEM] Scraping free background news for: {query}")
    ddg_url = f"https://html.duckduckgo.com/html/?q={query}+latest+news"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = requests.get(ddg_url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            result = soup.find('a', class_='result__snippet')
            return result.text.strip() if result else None
        return None
    except Exception as e:
        print(f"[DDG FAIL] {e}")
        return None

def extract_top_interest(interest_matrix):
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
