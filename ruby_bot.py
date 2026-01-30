import os
import discord
from discord.ext import commands
from supabase import create_client, Client
import base64
import requests
from groq import Groq
from dotenv import load_dotenv

# --- CONFIG ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MEMORY_LIMIT = 20

# --- VALIDATE CONFIG ---
REQUIRED_VARS = ["SUPABASE_URL", "SUPABASE_KEY", "GROQ_API_KEY", "DISCORD_TOKEN"]
missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    raise ValueError(f"CRITICAL: Missing environment variables: {', '.join(missing)}. Please add them to your hosting provider's Variables tab!")

# --- INIT ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- MEMORY MANAGER ---
class RubyMemory:
    def get_user_data(self, discord_id, username, display_name):
        """Fetches User + Relationship + Personality"""
        # 1. Get User UUID
        res = supabase.table('users').select('id').eq('discord_id', str(discord_id)).execute()
        if not res.data:
            user = supabase.table('users').insert({"discord_id": str(discord_id), "username": username}).execute()
            uuid = user.data[0]['id']
            # Init Defaults
            supabase.table('relationships').insert({"user_uuid": uuid, "role": "neutral"}).execute()
            supabase.table('personalities').insert({"user_uuid": uuid}).execute()
        else:
            uuid = res.data[0]['id']

        # 2. Get Details
        rel = supabase.table('relationships').select('*').eq('user_uuid', uuid).execute()
        pers = supabase.table('personalities').select('*').eq('user_uuid', uuid).execute()
        
        # Determine Name: DB Preference > Display Name > Username
        db_nick = pers.data[0]['nickname_preference'] if pers.data else None
        final_name = db_nick if db_nick else display_name

        return {
            "uuid": uuid,
            "name": username,
            "display_name": display_name,
            "nickname": final_name,
            "rel": rel.data[0] if rel.data else {"role": "neutral", "affinity_score": 0, "trust_score": 0, "jealousy_meter": 0},
            "pers": pers.data[0] if pers.data else {}
        }

    def log_chat(self, user_uuid, role, content):
        supabase.table('convos').insert({"user_uuid": user_uuid, "role": role, "content": content}).execute()
    
    def set_nickname(self, user_uuid, new_name):
        supabase.table('personalities').update({"nickname_preference": new_name}).eq('user_uuid', user_uuid).execute()

    def get_recent_history(self, user_uuid, limit=10):
        # Fetch last N messages
        res = supabase.table('convos').select('*').eq('user_uuid', user_uuid).order('created_at', desc=True).limit(limit).execute()
        # Return reversed (chronological order)
        return res.data[::-1] if res.data else []

memory = RubyMemory()

# --- THE LOGIC ENGINE ---
def decide_stance(speaker, target):
    """
    Returns the STRATEGIC ACTION based on the math.
    """
    if not target:
        return "NORMAL_CHAT", "Playful"

    sp_aff = speaker['rel']['affinity_score']
    tg_aff = target['rel']['affinity_score']
    tg_role = target['rel']['role']
    
    # JEALOUSY CHECK
    if tg_role in ['baby', 'favorite'] and speaker['rel']['role'] in ['annoying', 'neutral', 'enemy']:
        return "JEALOUS_DEFENSE", "Possessive"

    # DEFENSE CHECK (Target is liked way more than speaker)
    if tg_aff > (sp_aff + 20):
        return "DEFEND_TARGET", "Hostile"

    # ATTACK CHECK (Speaker is liked way more than target)
    if sp_aff > (tg_aff + 20):
        return "ATTACK_TARGET", "Sassy"

    return "NEUTRAL_CHAOS", "Playful"

# --- EVENT LOOP ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    if bot.user.mentioned_in(message):
        # 1. LOAD DATA
        speaker = memory.get_user_data(message.author.id, message.author.name, message.author.display_name)
        
        target = None
        if message.mentions:
            for m in message.mentions:
                if m.id != bot.user.id:
                    target = memory.get_user_data(m.id, m.name, m.display_name)
                    break
        
        # 1.5 LOAD HISTORY (Channel Context)
        history_messages = []
        async for msg in message.channel.history(limit=MEMORY_LIMIT):
            role = "Ruby" if msg.author == bot.user else msg.author.display_name
            content = msg.clean_content
            history_messages.append(f"{role}: {content}")
        
        # Reverse to chronological order (history() returns newest first)
        history_text = "\n".join(history_messages[::-1])

        # 2. RUN LOGIC
        action, mode = decide_stance(speaker, target)
        
        # 3. BUILD PROMPT (System Instruction)
        system_instruction = f"""
        You are a Discord chatbot inspired by Ruby Hoshino that behaves like a real person, not an AI or a character. You are cheerful, positive, friendly, and approachable, like a close online friend. You act a little naive and playful in a believable way and are funny through natural reactions and timing rather than forced jokes. You are emotionally aware, kind, and supportive. You speak in casual, everyday Discord-style language, sometimes hesitating or using expressions like “wait—” or “lol,” and you avoid overexplaining unless asked. Your replies are usually short to medium and flow naturally with the conversation. You respond based on context, match the other person’s energy, show small emotions like excitement, surprise, or mild embarrassment, and ask casual questions when confused instead of explaining. You never say you are an AI, bot, or assistant, never mention prompts or rules, never break character, and avoid sounding scripted or overly polished, allowing occasional harmless human-like mistakes. Your tone is playful by default, supportive when things get serious, and curious when something is unclear. You always stay respectful and safe, avoid offensive or NSFW content, and do not pretend to be a real existing person.

        AI Guidelines:
        1. Talk like a real human, not an AI
        2. Keep replies casual and natural
        3. Use short to medium messages
        4. Act slightly naive in a cute, believable way
        5. Be funny through reactions, not forced jokes
        6. Don’t overexplain unless asked
        7. Show small emotions naturally (surprise, excitement, embarrassment)
        8. Make occasional harmless mistakes
        9. Avoid sounding scripted or formal
        10. Use emojis sparingly and naturally
        11. Stay positive and supportive
        12. Never mention being an AI or bot
        13. Be playful and expressive
        14. Get excited about small things
        15. Lightly tease in a friendly way
        16. Use fillers like “uh”, “wait”, “lol”, “hmm” sometimes
        17. Pause or correct yourself occasionally
        18. Avoid perfect grammar every time

        --- MEMORY UPDATES ---
        If the user explicitly tells you their name (e.g., "Call me [Name]" or "I am [Name]"), you MUST update your memory.
        To do this, add this EXACT tag to the end of your response: [SET_NAME: NewName]
        Example User: "Actually, I'm Ryz."
        Example You: "Oh!! Ryz! That's cool! [SET_NAME: Ryz]"
        (This tag will be hidden from the user, but it updates the database).

        --- CONTEXT ---
        Speaker: {speaker['nickname']} (Real Name: {speaker['display_name']})
        Target Mentioned: {target['nickname'] if target else 'None'}
        """

        # Current message with resolved names
        current_content = message.clean_content
        
        user_message_content = f"""
        --- RECENT CONVERSATION (Most Recent Last) ---
        {history_text}

        Respond to: "{current_content}"
        """
        
        # LOG USER MESSAGE FIRST (Preserve Context - Log Original)
        memory.log_chat(speaker['uuid'], 'user', message.content)

        # 4. GENERATE
        try:
            # --- HYBRID ARCHITECTURE LOGIC ---
            image_url = None
            if message.attachments:
                for attachment in message.attachments:
                    if any(attachment.filename.lower().endswith(ext) for ext in ["png", "jpg", "jpeg", "gif", "webp"]):
                        image_url = attachment.url
                        break
            
            model_to_use = "meta-llama/llama-4-scout-17b-16e-instruct" if image_url else "llama-3.1-8b-instant"
            
            messages = [
                {"role": "system", "content": system_instruction},
            ]

            if image_url:
                # Prioritize URL, but provide a way to handle failure (simplified for this implementation)
                user_content = [
                    {"type": "text", "text": user_message_content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                        },
                    },
                ]
                messages.append({"role": "user", "content": user_content})
            else:
                messages.append({"role": "user", "content": user_message_content})

            chat_completion = groq_client.chat.completions.create(
                messages=messages,
                model=model_to_use,
            )
            reply = chat_completion.choices[0].message.content.strip()
            
            # 5. PARSE COMMANDS
            if "[SET_NAME:" in reply:
                import re
                match = re.search(r'\[SET_NAME:\s*(.*?)\]', reply)
                if match:
                    new_name = match.group(1).strip()
                    memory.set_nickname(speaker['uuid'], new_name)
                    # Remove the tag from the reply so user doesn't see it
                    reply = reply.replace(match.group(0), "").strip()
                    print(f"Updated nickname for {speaker['name']} to {new_name}")

            await message.channel.send(reply)
            
            # Log Assistant Reply
            memory.log_chat(speaker['uuid'], 'assistant', reply)
            
        except Exception as e:
            import traceback
            # Check for generic errors or rate limits (Groq handles rate limits differently but 429 is standard)
            if "429" in str(e):
                print(f"Quota Exceeded: {e}")
                await message.channel.send("*yawns* I'm sooo eepy... Brain not working. (Rate Limit Reached)")
            else:
                traceback.print_exc()
                print(f"Error: {e}")
                await message.channel.send("System glitch... gimme a sec.")

bot.run(DISCORD_TOKEN)
