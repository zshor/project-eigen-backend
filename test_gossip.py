import os
import requests
from groq import Groq
from bs4 import BeautifulSoup
from supabase import create_client, Client
from dotenv import load_dotenv

# Load the secret keys from your .env file
load_dotenv()

# Initialize Clients
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
supabase_url: str = os.environ.get("SUPABASE_URL")
supabase_key: str = os.environ.get("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env file")

supabase: Client = create_client(supabase_url, supabase_key)

def extract_top_interest(interest_matrix):
    """
    Recursively traverses the Supabase JSON to find the entity with the highest weight.
    """
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
    """
    Performs a lightweight, free web search using DuckDuckGo Lite.
    """
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
    """
    Synthesizes the web currency with the mutated prompt using Groq.
    """
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

def test_the_sandbox():
    print("--- STARTING GOSSIP ENGINE TEST ---")
    test_user_id = "test_hacker_123"

    print("1. Seeding database with dummy interest: 'Local LLM training and Llama 3'")
    supabase.table("user_cognitive_state").upsert({
        "user_id": test_user_id,
        "interest_matrix": {"artificial_intelligence": {"local_llm_training": {"weight": 95}}},
        "mutated_prompt": "The user is trying to run Llama 3 locally. Ask them what hardware they are running it on.",
        "current_mode": "SOCRATIC_GOSSIP"
    }).execute()

    user_data = supabase.table("user_cognitive_state").select("*").eq("user_id", test_user_id).execute().data[0]
    
    # We use a hardcoded topic to ensure the web search finds good data for the test
    top_interest = "local llm training Llama 3" 
    print(f"2. Performing Web Search for: {top_interest}")
    
    web_snippet = fetch_web_currency(top_interest)
    
    if not web_snippet:
        web_snippet = "No search results found today, but Llama 3 community fine-tunes keep dropping on HuggingFace."
        
    print(f"   -> Found Web Currency: {web_snippet[:80]}...")

    print("3. Generating Socratic Gossip Message via Groq...")
    gossip_message = generate_gossip_catalyst(top_interest, web_snippet, user_data['mutated_prompt'])
    
    print("\n====================================")
    print("FINAL PUSH NOTIFICATION OUTPUT:")
    print(gossip_message)
    print("====================================\n")

if __name__ == "__main__":
    test_the_sandbox()
