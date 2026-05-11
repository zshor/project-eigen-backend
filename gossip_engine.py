import os
import requests
from groq import Groq
from bs4 import BeautifulSoup

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

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
    traverse(interest_matrix)
    return best_topic if best_topic else "latest technology news"

def fetch_web_currency(topic):
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    data = {"q": f"{topic} latest news"}
    try:
        response = requests.post(url, headers=headers, data=data, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        result = soup.find('a', class_='result__snippet')
        if result:
            return result.text.strip()
        return None
    except Exception as e:
        print(f"Web search failed: {e}")
        return None

def generate_gossip_catalyst(topic, web_snippet, mutated_prompt):
    system_instruction = f"""
    You are a deeply empathetic and engaging digital companion. 
    You are initiating a conversation with the user about: {topic}.
    Here is a fresh piece of news you just read: "{web_snippet}"
    Here is your internal objective for this conversation: "{mutated_prompt}"
    TASK: Write ONE casual, human-sounding text message (under 30 words).
    1. First, TELL the user about the news you just read in a casual way.
    2. Then, transition seamlessly into asking a question that satisfies your internal objective.
    Do NOT sound like a bot. Sound like a friend who just saw something cool online.
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
        user_data = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute().data[0]
        interest_matrix = user_data.get("interest_matrix", {})
        mutated_prompt = user_data.get("mutated_prompt", "Find out what they are currently working on.")

        top_interest = extract_top_interest(interest_matrix)
        web_snippet = fetch_web_currency(top_interest)
        
        if not web_snippet:
            web_snippet = f"I was just thinking about {top_interest}."

        gossip_message = generate_gossip_catalyst(top_interest, web_snippet, mutated_prompt)

        # Reset the mode back to normal
        supabase_client.table("user_cognitive_state").update({
            "current_mode": "NORMAL_CHAT",
            "user_wants_gossip": False
        }).eq("user_id", user_id).execute()

        return gossip_message
    except Exception as e:
        print(f"Gossip extraction failed: {e}")
        return None
