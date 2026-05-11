import firebase_admin
from firebase_admin import credentials, messaging

print("\n=== THE MIRROR: PUSH DIAGNOSTIC ===")

try:
    # 1. Initialize Firebase
    cred = credentials.Certificate("firebase-admin-key.json")
    default_app = firebase_admin.initialize_app(cred)
    print(f"[OK] Authenticated to Backend Project: {default_app.project_id}")
except Exception as e:
    print(f"[FATAL] Could not load JSON key: {e}")
    exit()

# 2. Your newly generated, cache-cleared token
TARGET_TOKEN = "cb6jXgfeQmGn3A0AZKrGyT:APA91bF5FeQizH72e_WTgNcnPDEi6vJVINmHUmUazIfwYUYR5jiu33rUpkr0zqk267OaFAn1oD59j504OhqPfIV3C-nf3SrOmvdu3EyipH5cn8ftCKvjqUA"
print(f"[OK] Target Token Loaded: {TARGET_TOKEN[:15]}...{TARGET_TOKEN[-10:]}")

def fire_diagnostic_whisper():
    try:
        print("[*] Building message payload...")
        message = messaging.Message(
            notification=messaging.Notification(
                title="The Mirror",
                body="Diagnostic Push Successful. The bridge is secure.",
            ),
            token=TARGET_TOKEN,
        )
        
        print("[*] Dispatching to Google servers...")
        response = messaging.send(message)
        
        print(f"\n[SUCCESS] Notification delivered!")
        print(f"Message ID: {response}\n")
        
    except messaging.UnregisteredError:
        print("\n[ERROR] UnregisteredError: Requested entity was not found.")
        print("-> MEANING: Google says this token belongs to an old/deleted installation.")
    except Exception as e:
        print(f"\n[ERROR] Failed to send: {e}")
        print(f"-> EXCEPTION TYPE: {type(e).__name__}\n")

if __name__ == "__main__":
    fire_diagnostic_whisper()
