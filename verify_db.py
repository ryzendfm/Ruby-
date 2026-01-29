import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def verify():
    print("--- Verifying Users ---")
    users = supabase.table('users').select('*').execute()
    if users.data:
        print(f"Found {len(users.data)} user(s):")
        for u in users.data:
            print(f"- {u['username']} (ID: {u['discord_id']})")
    else:
        print("No users found!")

    print("\n--- Verifying Conversations ---")
    convos = supabase.table('convos').select('*').order('created_at', desc=True).limit(5).execute()
    if convos.data:
        print(f"Found recent conversations (showing last 5):")
        for c in convos.data:
            print(f"[{c['role']}] {c['content']}")
    else:
        print("No conversations log found!")

if __name__ == "__main__":
    verify()
