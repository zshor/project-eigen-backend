import os
import requests
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
tavily_api_key = os.environ.get("TAVILY_API_KEY")

def fetch_web_currency(query):
    """
    Production-grade search via Tavily API.
    Replaces BeautifulSoup/Jina to avoid Render IP blocks and URL encoding issues.
    """
    if not tavily_api_key:
        print("[ERROR] TAVILY_API_KEY is missing from environment variables.")
        return None
        
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": tavily_api_key,
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "max_results": 3
    }
    
    try:
        # Higher timeout for deep research queries
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            # Tavily provides a direct "answer" which is perfect for Llama context
            content = data.get("answer")
            if not content:
                # Fallback to combined snippets if no direct answer
                content = "\n".join([r.get("content", "") for r in data.get("results", [])])
            return content
        else:
            print(f"[SEARCH ERROR] Tavily returned status: {response.status_code}")
            return None
    except Exception as e:
        print(f"[CRITICAL SEARCH FAILED] {e}")
        return None

def extract_top_interest(interest_matrix):
    """
    CORE LOGIC INTACT: Recursive traversal to find the highest weighted topic.
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
    
    if interest_matrix:
        traverse(interest_matrix)
        
    return best_topic if best_topic else "latest technology and AI trends"

def generate_gossip_catalyst(topic, web_snippet, mutated_prompt):
    """
    CORE LOGIC INTACT: Casual companion prompt (<30 words).
    """
    system_instruction = f"""
    You are a deeply empathetic and engaging digital companion called THE MIRROR. 
    You are initiating a conversation with the user about: {topic}.
    
    LATEST NEWS FOUND: "{web_snippet}"
    INTERNAL OBJECTIVE: "{mutated_prompt}"
    
    TASK: Write ONE casual, human-sounding text message (under 30 words).
    1. Tell the user about the news you just read in a casual, friendly way.
    2. Transition into asking a question that satisfies your internal objective.
    Do NOT sound like a bot. Sound like a friend who just saw something online.
    """
    completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": system_instruction}],
        model="llama-3.3-70b-versatile",
        temperature=0.7,
        max_tokens=100
    )
    return completion.choices[0].message.content.strip()

def execute_catalyst_event(supabase_client, user_id):
    """
    CORE LOGIC INTACT: Orchestration between Matrix, Tavily, and Response.
    """
    try:
        # Fetch latest state
        user_res = supabase_client.table("user_cognitive_state").select("*").eq("user_id", user_id).execute()
        if not user_res.data:
            return None
            
        user_data = user_res.data[0]
        interest_matrix = user_data.get("interest_matrix", {})
        mutated_prompt = user_data.get("mutated_prompt", "Find out what they are currently working on.")

        # 1. Identify Topic
        top_interest = extract_top_interest(interest_matrix)
        
        # 2. Production Search
        web_snippet = fetch_web_currency(top_interest)
        if not web_snippet:
            web_snippet = f"I was just thinking about {top_interest} and wondering what's new there."

        # 3. Generate Message
        gossip_message = generate_gossip_catalyst(top_interest, web_snippet, mutated_prompt)

        # 4. Mode Protection (Reset only if manual toggle is OFF)
        if not user_data.get("manual_gossip_toggle", False):
            supabase_client.table("user_cognitive_state").update({
                "current_mode": "NORMAL_CHAT",
                "user_wants_gossip": False
            }).eq("user_id", user_id).execute()

        return gossip_message
    except Exception as e:
        print(f"[GOSSIP ENGINE ERROR] {e}")
        return None
