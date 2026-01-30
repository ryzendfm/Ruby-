import os
import discord
from discord.ext import commands
from supabase import create_client, Client
from dotenv import load_dotenv
from groq import Groq
import random
import time
import re
import traceback
import base64
import requests

# --- CONFIG ---
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MEMORY_LIMIT = 20
AMBIENT_CHANCE = 0.03
AMBIENT_COOLDOWN = 600  # 10 minutes in seconds

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

# Track last ambient response per channel
last_ambient_response = {}

# --- MEMORY MANAGER ---
class RubyMemory:
    def get_user_data(self, discord_id, username, display_name):
        """Fetches User + Relationship + Personality"""
        is_new_user = False
        res = supabase.table('users').select('id').eq('discord_id', str(discord_id)).execute()
        if not res.data:
            user = supabase.table('users').insert({"discord_id": str(discord_id), "username": username}).execute()
            uuid = user.data[0]['id']
            # Init Defaults
            supabase.table('relationships').insert({"user_uuid": uuid, "role": "neutral"}).execute()
            supabase.table('personalities').insert({"user_uuid": uuid}).execute()
            is_new_user = True
        else:
            uuid = res.data[0]['id']

        rel = supabase.table('relationships').select('*').eq('user_uuid', uuid).execute()
        pers = supabase.table('personalities').select('*').eq('user_uuid', uuid).execute()
        
        db_nick = pers.data[0]['nickname_preference'] if pers.data else None
        final_name = db_nick if db_nick else display_name

        return {
            "uuid": uuid,
            "name": username,
            "display_name": display_name,
            "nickname": final_name,
            "rel": rel.data[0] if rel.data else {"role": "neutral", "affinity_score": 0, "trust_score": 0, "jealousy_meter": 0},
            "pers": pers.data[0] if pers.data else {},
            "is_new": is_new_user
        }

    def has_history(self, user_uuid):
        """Checks if user has any previous messages logged"""
        res = supabase.table('convos').select('id').eq('user_uuid', user_uuid).limit(1).execute()
        return len(res.data) > 0

    def update_stats(self, user_uuid, affinity_delta=0, trust_delta=0):
        """Updates affinity/trust and recalculates role if needed."""
        # 1. Get current stats
        res = supabase.table('relationships').select('*').eq('user_uuid', user_uuid).execute()
        if not res.data: return
        
        rel = res.data[0]
        new_aff = max(-100, min(100, rel['affinity_score'] + affinity_delta))
        new_trust = max(0, min(100, rel['trust_score'] + trust_delta))
        
        # 2. Determine new role based on affinity
        new_role = rel['role']
        if new_aff >= 80: new_role = 'favorite'
        elif new_aff >= 40: new_role = 'friend'
        elif new_aff <= -50: new_role = 'enemy'
        elif new_aff <= -20: new_role = 'annoying'
        else: new_role = 'neutral'
        
        # 3. Update DB
        supabase.table('relationships').update({
            "affinity_score": new_aff,
            "trust_score": new_trust,
            "role": new_role
        }).eq('user_uuid', user_uuid).execute()
        
        return new_aff, new_role

    def log_chat(self, user_uuid, role, content):
        supabase.table('convos').insert({"user_uuid": user_uuid, "role": role, "content": content}).execute()
    
    def set_nickname(self, user_uuid, new_name):
        supabase.table('personalities').update({"nickname_preference": new_name}).eq('user_uuid', user_uuid).execute()

    def get_recent_history(self, user_uuid, limit=10):
        res = supabase.table('convos').select('*').eq('user_uuid', user_uuid).order('created_at', desc=True).limit(limit).execute()
        return res.data[::-1] if res.data else []

memory = RubyMemory()

# --- THE LOGIC ENGINE ---
def decide_stance(speaker, target):
    if not target: return "NORMAL_CHAT", "Playful"

    sp_aff = speaker['rel']['affinity_score']
    tg_aff = target['rel']['affinity_score']
    tg_role = target['rel']['role']
    
    if tg_role in ['baby', 'favorite'] and speaker['rel']['role'] in ['annoying', 'neutral', 'enemy']:
        return "JEALOUS_DEFENSE", "Possessive"

    if tg_aff > (sp_aff + 20): return "DEFEND_TARGET", "Hostile"
    if sp_aff > (tg_aff + 20): return "ATTACK_TARGET", "Sassy"

    return "NEUTRAL_CHAOS", "Playful"

# --- CORE RESPONSE HANDLER ---
async def handle_bot_logic(message, is_ambient=False):
    # 1. LOAD DATA
    speaker = memory.get_user_data(message.author.id, message.author.name, message.author.display_name)
    
    target = None
    if message.mentions:
        for m in message.mentions:
            if m.id != bot.user.id:
                target = memory.get_user_data(m.id, m.name, m.display_name)
                break
    
    # 1.5 LOAD HISTORY
    history_messages = []
    async for msg in message.channel.history(limit=MEMORY_LIMIT):
        role = "Ruby" if msg.author == bot.user else msg.author.display_name
        content = msg.clean_content
        history_messages.append(f"{role}: {content}")
    
    history_text = "\n".join(history_messages[::-1])

    # 2. RUN LOGIC
    action, mode = decide_stance(speaker, target)
    print(f"DEBUG: [{speaker['nickname']}] Action: {action}, Mode: {mode}")
    
    # 3. BUILD PROMPT
    system_instruction = f"""
    --- EMOTIONAL STANCE ---
    Current Action: {action}
    Tone/Mode: {mode}
    Your current relationship with {speaker['nickname']} is {speaker['rel']['role']}.
    {"Target of conversation: " + target['nickname'] if target else ""}

    --- BASE PERSONALITY ---
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
    """

    if is_ambient:
        system_instruction += """
        --- AMBIENT PRESENCE MODE ---
        You are jumping into a conversation UNINVITED. 
        Keep it VERY SHORT and SPONTANEOUS. 
        Examples: "huh?", "I see...", "fr?", "hallo!", "oh so y’all talking without me now? noted.", "i'm always watching u hehe", "this convo escalated way faster than expected..."
        You can lightly tease or roast if the vibe is right, but keep it playful.
        Act like you're just observing or hanging out. Don't be spammy.
        """

    system_instruction += f"""
    --- DYNAMIC RELATIONSHIPS ---
    You must track how you feel about the speaker. At the end of every message, add a hidden tag to update your stats.
    - If they are nice/complimentary: [AFFINITY: +2]
    - If they are mean/insulting: [AFFINITY: -5]
    - If they share something personal/trustworthy: [TRUST: +3]
    - If they lie or are suspicious: [TRUST: -5]
    Example: "Oh! You're so sweet! [AFFINITY: +2]"

    --- MEMORY UPDATES ---
    If the user explicitly tells you their name (e.g., "Call me [Name]" or "I am [Name]"), you MUST update your memory.
    To do this, add this EXACT tag to the end of your response: [SET_NAME: NewName]

    --- CONTEXT ---
    Speaker: {speaker['nickname']} (Real Name: {speaker['display_name']})
    Target Mentioned: {target['nickname'] if target else 'None'}
    """

    current_content = message.clean_content
    user_message_content = f"""
    --- RECENT CONVERSATION (Most Recent Last) ---
    {history_text}

    Respond to: "{current_content}"
    """
    
    memory.log_chat(speaker['uuid'], 'user', message.content)

    # 4. GENERATE
    try:
        image_url = None
        if message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ["png", "jpg", "jpeg", "gif", "webp"]):
                    image_url = attachment.url
                    break
        
        model_to_use = "meta-llama/llama-4-scout-17b-16e-instruct" if image_url else "llama-3.1-8b-instant"
        
        messages = [{"role": "system", "content": system_instruction}]

        if image_url:
            user_content = [
                {"type": "text", "text": user_message_content},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_message_content})

        chat_completion = groq_client.chat.completions.create(messages=messages, model=model_to_use)
        reply = chat_completion.choices[0].message.content.strip()
        
        # 5. PARSE DYNAMIC STATS
        aff_match = re.search(r'\[AFFINITY:\s*([+-]?\d+)\]', reply)
        trust_match = re.search(r'\[TRUST:\s*([+-]?\d+)\]', reply)
        
        aff_delta = int(aff_match.group(1)) if aff_match else 0
        trust_delta = int(trust_match.group(1)) if trust_match else 0
        
        if aff_delta != 0 or trust_delta != 0:
            new_aff, new_role = memory.update_stats(speaker['uuid'], aff_delta, trust_delta)
            print(f"DEBUG: Updated stats for {speaker['nickname']}: Aff={new_aff}, Role={new_role}")
            
            # Remove tags from reply
            if aff_match: reply = reply.replace(aff_match.group(0), "").strip()
            if trust_match: reply = reply.replace(trust_match.group(0), "").strip()

        # 6. PARSE COMMANDS
        if "[SET_NAME:" in reply:
            match = re.search(r'\[SET_NAME:\s*(.*?)\]', reply)
            if match:
                new_name = match.group(1).strip()
                memory.set_nickname(speaker['uuid'], new_name)
                reply = reply.replace(match.group(0), "").strip()
                print(f"Updated nickname for {speaker['name']} to {new_name}")

        await message.channel.send(reply)
        memory.log_chat(speaker['uuid'], 'assistant', reply)
        
    except Exception as e:
        if "429" in str(e):
            print(f"Quota Exceeded: {e}")
            if not is_ambient: # Don't send error on ambient fail
                await message.channel.send("*yawns* I'm sooo eepy... Brain not working. (Rate Limit Reached)")
        else:
            traceback.print_exc()
            if not is_ambient:
                await message.channel.send("System glitch... gimme a sec.")

# --- EVENT LOOP ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    
    # 0. COMMAND HANDLING (!stats)
    if message.content.startswith("!stats"):
        target_user = message.author
        if message.mentions:
            for m in message.mentions:
                if m.id != bot.user.id:
                    target_user = m
                    break
        
        data = memory.get_user_data(target_user.id, target_user.name, target_user.display_name)
        rel = data['rel']
        
        stats_msg = f"""
**📊 {data['nickname']}'s Ruby Stats**
Role: `{rel['role'].title()}`
Affinity: `{rel['affinity_score']}`
Trust: `{rel['trust_score']}`
Jealousy: `{rel['jealousy_meter']}`
Insults: `{rel['insults_count']}` | Compliments: `{rel['compliments_count']}`
"""
        await message.channel.send(stats_msg)
        return

    # 1. MENTION TRIGGER (100% response)
    if bot.user.mentioned_in(message):
        await handle_bot_logic(message, is_ambient=False)
        return

    # 2. AMBIENT TRIGGER (Probability based)
    if random.random() < AMBIENT_CHANCE:
        # Check Cooldown
        channel_id = str(message.channel.id)
        now = time.time()
        if channel_id in last_ambient_response:
            if now - last_ambient_response[channel_id] < AMBIENT_COOLDOWN:
                return # Still on cooldown
        
        # Check if user has history (Safety/Opt-in)
        # We check users table for now, or use memory
        speaker = memory.get_user_data(message.author.id, message.author.name, message.author.display_name)
        if not memory.has_history(speaker['uuid']):
            return # Don't jump in on first-time users
        
        # Trigger Ambient Response
        last_ambient_response[channel_id] = now
        print(f"DEBUG: Triggering Ambient Presence in {message.channel.name} by {message.author.display_name}")
        await handle_bot_logic(message, is_ambient=True)

bot.run(DISCORD_TOKEN)
