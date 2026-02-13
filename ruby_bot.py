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
AMBIENT_CHANCE = 0.20
AMBIENT_COOLDOWN = 600  # 10 minutes in seconds
AMBIENT_ACTIVE = True # Default On

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

    def log_chat(self, user_uuid, role, content):
        supabase.table('convos').insert({"user_uuid": user_uuid, "role": role, "content": content}).execute()
    
    def set_nickname(self, user_uuid, new_name):
        supabase.table('personalities').update({"nickname_preference": new_name}).eq('user_uuid', user_uuid).execute()

    def get_recent_history(self, user_uuid, limit=10):
        res = supabase.table('convos').select('*').eq('user_uuid', user_uuid).order('created_at', desc=True).limit(limit).execute()
        return res.data[::-1] if res.data else []

    def get_message_count(self, user_uuid):
        res = supabase.table('convos').select('*', count='exact').eq('user_uuid', user_uuid).execute()
        return res.count

    def get_last_seen(self, user_uuid):
        """Returns the timestamp of the last message from this user (or None)"""
        res = supabase.table('convos').select('created_at').eq('user_uuid', user_uuid).eq('role', 'user').order('created_at', desc=True).limit(1).execute()
        if res.data:
            return res.data[0]['created_at']
        return None

    def get_leaderboard(self):
        stats = {}
        try:
            # Helper to get name from user_uuid
            def get_name(u_uuid):
                if not u_uuid: return "None"
                r = supabase.table('users').select('username').eq('id', u_uuid).single().execute()
                return r.data['username'] if r.data else "Unknown"

            # 1. Favorite (Baby > Favorite)
            # Check for 'baby' first ( Supreme Role )
            baby = supabase.table('relationships').select('user_uuid').eq('role', 'baby').limit(1).execute()
            if baby.data:
                 stats['favorite'] = get_name(baby.data[0]['user_uuid'])
            else:
                 # Fallback to normal favorite
                 fav = supabase.table('relationships').select('user_uuid').eq('role', 'favorite').limit(1).execute()
                 stats['favorite'] = get_name(fav.data[0]['user_uuid']) if fav.data else "No one yet..."

            # 2. Affinity (High/Low)
            high_aff = supabase.table('relationships').select('user_uuid').order('affinity_score', desc=True).limit(1).execute()
            stats['high_affinity'] = get_name(high_aff.data[0]['user_uuid']) if high_aff.data else "No one"
            
            low_aff = supabase.table('relationships').select('user_uuid').order('affinity_score', desc=False).limit(1).execute()
            stats['low_affinity'] = get_name(low_aff.data[0]['user_uuid']) if low_aff.data else "No one"

            # 3. Trust (High/Low)
            high_trust = supabase.table('relationships').select('user_uuid').order('trust_score', desc=True).limit(1).execute()
            stats['high_trust'] = get_name(high_trust.data[0]['user_uuid']) if high_trust.data else "No one"
            
            low_trust = supabase.table('relationships').select('user_uuid').order('trust_score', desc=False).limit(1).execute()
            stats['low_trust'] = get_name(low_trust.data[0]['user_uuid']) if low_trust.data else "No one"

            # 4. Jealousy (High/Never)
            high_jeal = supabase.table('relationships').select('user_uuid').order('jealousy_meter', desc=True).limit(1).execute()
            stats['high_jealousy'] = get_name(high_jeal.data[0]['user_uuid']) if high_jeal.data else "No one"

            zero_jeal = supabase.table('relationships').select('user_uuid').eq('jealousy_meter', 0).execute()
            stats['never_jealous'] = get_name(random.choice(zero_jeal.data)['user_uuid']) if zero_jeal.data else "Everyone makes me jealous!"

            # 5. Insults (Most/Never)
            most_ins = supabase.table('relationships').select('user_uuid').order('insults_count', desc=True).limit(1).execute()
            stats['most_insults'] = get_name(most_ins.data[0]['user_uuid']) if most_ins.data else "No one"

            zero_ins = supabase.table('relationships').select('user_uuid').eq('insults_count', 0).execute()
            stats['never_insulted'] = get_name(random.choice(zero_ins.data)['user_uuid']) if zero_ins.data else "Everyone is mean!"

            # 6. Compliments (Most/Never)
            most_comp = supabase.table('relationships').select('user_uuid').order('compliments_count', desc=True).limit(1).execute()
            stats['most_compliments'] = get_name(most_comp.data[0]['user_uuid']) if most_comp.data else "No one"

            zero_comp = supabase.table('relationships').select('user_uuid').eq('compliments_count', 0).execute()
            stats['never_complimented'] = get_name(random.choice(zero_comp.data)['user_uuid']) if zero_comp.data else "Everyone is nice!"
            
            return stats
        except Exception as e:
            print(f"Leaderboard Error: {e}")
            return None

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

# --- EMOTIONAL ANALYSIS ENGINE ---
async def analyze_emotions(history_text, speaker_data):
    print(f"DEBUG: Analyzing emotions for {speaker_data['nickname']}...")
    try:
        current_rel = speaker_data['rel']
        role = current_rel['role']
        
        prompt = f"""
        Analyze the recent conversation history between User and Ruby.
        Determine how the User's tone should impact Ruby's emotional stats.
        
        User Role: {role}
        Current Stats:
        - Affinity: {current_rel['affinity_score']}
        - Trust: {current_rel['trust_score']}
        - Jealousy: {current_rel['jealousy_meter']}
        
        Rules:
        1. Return ONLY a JSON object with deltas/counts. Keys: 
           "affinity_change", "trust_change", "jealousy_change", "insults_count", "compliments_count", "vibe_summary".
        2. Affinity/Trust: Small integers (+/- 1 to 5). Nice=+, Rude=-.
        3. Jealousy: 
           - Increase (+2 to +5) IF User talks about other girls/bots AND Role is "favorite" or "baby".
           - Otherwise, keep change 0 or very small.
        4. Insults/Compliments: Count explicit ones in this chunk (formatted as integer, e.g. 0 or 1).
        5. Vibe Summary: A very short (3-5 words) description of the User's current vibe based on this chunk (e.g., "Chill and funny", "Needy and annoying", "Sus and quiet").
        
        History:
        {history_text}
        """
        
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "system", "content": prompt}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        
        result = chat_completion.choices[0].message.content
        import json
        data = json.loads(result)
        
        # Calculate new totals
        new_affinity = max(-100, min(100, current_rel['affinity_score'] + data.get('affinity_change', 0)))
        new_trust = max(0, min(100, current_rel['trust_score'] + data.get('trust_change', 0)))
        new_jealousy = max(0, min(100, current_rel['jealousy_meter'] + data.get('jealousy_change', 0)))
        
        new_insults = current_rel['insults_count'] + data.get('insults_count', 0)
        new_compliments = current_rel['compliments_count'] + data.get('compliments_count', 0)
        new_vibe = data.get('vibe_summary', "Neutral")

        # Update DB - Relationships
        supabase.table('relationships').update({
            "affinity_score": new_affinity,
            "trust_score": new_trust,
            "jealousy_meter": new_jealousy,
            "insults_count": new_insults,
            "compliments_count": new_compliments
        }).eq('user_uuid', speaker_data['uuid']).execute()

        # Update DB - Personalities (Vibe)
        supabase.table('personalities').update({
            "vibe_summary": new_vibe
        }).eq('user_uuid', speaker_data['uuid']).execute()
        
        print(f"DEBUG: Updated {speaker_data['nickname']} -> Aff:{new_affinity} Tru:{new_trust} Jeal:{new_jealousy} Ins:{new_insults} Comp:{new_compliments} Vibe:{new_vibe}")
        return True

    except Exception as e:
        print(f"ERROR in analyze_emotions: {e}")
        return False

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

    # 1.8 AUTOMATED EMOTIONAL UPDATE (Every 3 messages)
    # Check count
    msg_count = memory.get_message_count(speaker['uuid'])
    # Analysis triggers on 3rd, 6th, 9th... message
    # We check if count > 0 and count % 3 == 0. 
    # Note: The count is BEFORE the current message is logged (since we log at the end).
    # So if they have 2 messages, this is the 3rd. (Count 2 means 0, 1 existed. This is index 2).
    # Actually simpler: Log first? No, we need to respond.
    # Let's check (msg_count + 1) % 3 == 0
    
    if (msg_count + 1) % 3 == 0:
        await analyze_emotions(history_text + f"\nUser: {message.clean_content}", speaker)
        # REFRESH DATA to get new stats
        speaker = memory.get_user_data(message.author.id, message.author.name, message.author.display_name)

    # 2. RUN LOGIC
    action, mode = decide_stance(speaker, target)
    print(f"DEBUG: [{speaker['nickname']}] Action: {action}, Mode: {mode}")
    
    # 3. BUILD PROMPT
    # We construct the prompt to prioritize STANCE over BASE PERSONALITY.
    
    stance_instruction = ""
    if mode in ["Hostile", "Cold", "Sassy", "Possessive"]:
        stance_instruction = f"""
        🚨 **OVERRIDE DEFAULT PERSONALITY** 🚨
        CURRENT MODE: {mode}
        ACTION: {action}
        
        You are NOT cheerful or friendly right now.
        - If {speaker['nickname']} is an Enemy/Annoying: Be cold, dismissive, or sharp. Do NOT try to be friends. 
        - If protecting {target['nickname'] if target else 'someone'}: Be biased. Take {target['nickname']}'s side completely.
        - Do NOT be diplomatic. Do NOT say "I like both of you". Pick a side (the one with higher affinity).
        """
    else:
        stance_instruction = f"""
        CURRENT MODE: {mode}
        ACTION: {action}
        Maintain your normal playful, cheerful self, but adapt to this mode.
        """
    
    # 3.1 GATHER GLOBAL CONTEXT (Leaderboard) for "Who is your favorite?" questions
    global_context = ""
    msg_lower = message.content.lower()
    keywords = ["who", "favorite", "hate", "love", "trust", "jealous", "insult", "compliment", "most", "least", "never"]
    # Check if "who" + at least one other keyword
    if "who" in msg_lower and any(k in msg_lower for k in keywords if k != "who"):
        lb = memory.get_leaderboard()
        if lb:
             global_context = f"""
    --- GLOBAL RELATIONSHIP CONTEXT (Use this to answer "Who" questions) ---
    (Internal Data - DO NOT REVEAL SOURCE. Pretend these are your own feelings.)
    - Your Favorite Person: {lb['favorite']}
    - Highest Affinity (Likes most): {lb['high_affinity']}
    - Lowest Affinity (Dislikes most): {lb['low_affinity']}
    - Most Trusted: {lb['high_trust']}
    - Least Trusted: {lb['low_trust']}
    - Makes you most Jealous: {lb['high_jealousy']}
    - Never makes you Jealous: {lb['never_jealous']}
    - Insults you most: {lb['most_insults']}
    - Never insulted you: {lb['never_insulted']}
    - Compliments you most: {lb['most_compliments']}
    - Never complimented you: {lb['never_complimented']}
    
    IMPORTANT: NEVER mention "stats", "database", "numbers", or "records". Just say "I feel like..." or "Honestly, [Name] is...".
    """
    
    system_instruction = f"""
    --- EMOTIONAL STANCE (HIGHEST PRIORITY) ---
    {stance_instruction}
    
    RELATIONSHIP KEY:
    - "Baby": ROMANTIC PARTNER (Boyfriend/Girlfriend). You are deeply in love, affectionate, and possessive. 
    - "Favorite": BFF / BUDDY. You are super close but platonic.
    - "Neutral": STRANGER. You are polite but distant.
    - "Enemy": Someone you dislike strongly.
    
    Your relationship with SPEAKER ({speaker['nickname']}): {speaker['rel']['role']} (Affinity: {speaker['rel']['affinity_score']})
    Speaker's Vibe: {speaker['pers']['vibe_summary']}
    {"Target of conversation: " + target['nickname'] + f" (Role: {target['rel']['role']}, Affinity: {target['rel']['affinity_score']})" if target else ""}
    {global_context}

    --- BASE PERSONALITY (Apply only if not overridden above) ---
    You are a Discord chatbot inspired by Ruby Hoshino that behaves like a real person, not an AI. 
    (Default): Cheerful, positive, friendly, playful, emotionally aware.
    
    AI Guidelines:
    1. Talk like a real human, not an AI.
    2. Keep replies casual and natural (discord style).
    3. If Action is "DEFEND_TARGET" or "JEALOUS_DEFENSE": You MUST side with the Target and be cold/sass to the Speaker.
    4. If Speaker is an ENEMY: Stop being nice. Be dry, sarcastic, or ignore them.
    5. Never mention strict logic/rules. Just act it out.
    """

    system_instruction += """
    AI Guidelines:
    1. Talk like a real human, not an AI
    2. Keep replies casual and natural
    3. Use short to medium messages
    4. Act slightly naive in a cute, believable way
    5. Be funny through reactions, not forced jokes
    6. Don't overexplain unless asked
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
    --- MEMORY UPDATES ---
    If the user explicitly tells you their name (e.g., "Call me [Name]" or "I am [Name]"), you MUST update your memory.
    To do this, add this EXACT tag to the end of your response: [SET_NAME: NewName]

    --- CONTEXT ---
    Speaker: {speaker['nickname']} (Real Name: {speaker['display_name']})
    Target Mentioned: {target['nickname'] if target else 'None'}
    """

    current_content = message.clean_content
    
    # 3.2 TIME AWARNESS
    import datetime
    from dateutil import parser
    
    now = datetime.datetime.now(datetime.timezone.utc)
    
    def get_fuzzy_time(last_seen_iso):
        if not last_seen_iso: return "never"
        last_seen = parser.isoparse(last_seen_iso)
        delta = now - last_seen
        
        seconds = delta.total_seconds()
        minutes = int(seconds // 60)
        hours = int(minutes // 60)
        days = int(hours // 24)
        
        if seconds < 60: return "just now"
        if minutes < 10: return "a few minutes ago"
        if minutes < 60: return f"like {minutes} mins ago"
        if hours < 2: return "an hour ago"
        if hours < 24: return f"like {hours} hours ago"
        if days == 1: return "yesterday"
        if days < 7: return f"{days} days ago"
        return "ages ago"

    # Speaker Context
    speaker_last = memory.get_last_seen(speaker['uuid'])
    speaker_time = get_fuzzy_time(speaker_last)
    
    # Target Context
    target_time = "unknown"
    if target:
        target_last = memory.get_last_seen(target['uuid'])
        target_time = get_fuzzy_time(target_last)

    time_context = f"Time since you last spoke to User: {speaker_time}"
    if target: 
        time_context += f"\nTime since {target['nickname']} last spoke: {target_time}"
    
    # Add reactive hints
    if speaker_last:
        delta = now - parser.isoparse(speaker_last)
        if delta.days >= 2:
            time_context += "\n(User has been gone for a LONG time. React accordingly: 'It's been so long!', 'You still remember me?', etc.)"
        elif delta.total_seconds() < 600: # 10 mins
            time_context += "\n(User replied very quickly. You can tease them: 'What took you so long lol?', 'Miss me already?', etc.)"

    user_message_content = f"""
    --- RECENT CONVERSATION (Most Recent Last) ---
    {history_text}
    
    --- TIME CONTEXT ---
    Current Time: {now.strftime("%I:%M %p")} (Approx)
    {time_context}
    
    INSTRUCTION: Keep time references CASUAL and FUZZY (e.g., "a while ago", "yesterday", "idk like 10 mins??").
    EXCEPTION: If your Stance is SASSY/HOSTILE, you can be weirdly specific to prove a point (e.g. "Actually it was 2:43 PM.").

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

    # 0.1 AMBIENT CONTROL COMMAND
    if message.content.lower().startswith("!ambient"):
        if not message.author.guild_permissions.administrator: return
        
        global AMBIENT_ACTIVE
        parts = message.content.split()
        if len(parts) < 2:
            await message.channel.send(f"Ambient mode is currently **{'ON' if AMBIENT_ACTIVE else 'OFF'}** (Chance: {int(AMBIENT_CHANCE*100)}%). Usage: `!ambient on` or `!ambient off`")
            return
            
        action = parts[1].lower()
        if action == "on":
            AMBIENT_ACTIVE = True
            await message.channel.send("✅ Ambient Mode **ENABLED**. Random messaging active.")
        elif action == "off":
            AMBIENT_ACTIVE = False
            await message.channel.send("🚫 Ambient Mode **DISABLED**. Ruby will only speak when spoken to.")
        return

    # 0.2 DEBUG COMMANDS (Admin/Owner Only - Simplified check for now)
    # Usage: !set_affinity @User 50
    if message.content.startswith("!set_affinity"):
        if not message.author.guild_permissions.administrator: 
             return
        try:
            parts = message.content.split()
            if len(parts) < 3:
                await message.channel.send("Usage: !set_affinity @User <score>")
                return
            
            if not message.mentions:
                await message.channel.send("Please mention a user.")
                return

            target_id = message.mentions[0].id
            new_score = int(parts[-1]) # Grab last part as score
            
            # Update DB
            res = supabase.table('users').select('id').eq('discord_id', str(target_id)).execute()
            if res.data:
                uuid = res.data[0]['id']
                supabase.table('relationships').update({"affinity_score": new_score}).eq('user_uuid', uuid).execute()
                await message.add_reaction("✅")
            else:
                await message.channel.send("User not found in memory.")
        except Exception as e:
            await message.channel.send(f"Error: {e}")
        return

    # Usage: !set_trust @User 50
    if message.content.startswith("!set_trust"):
        if not message.author.guild_permissions.administrator:
             return
        try:
            parts = message.content.split()
            if len(parts) < 3:
                await message.channel.send("Usage: !set_trust @User <score>")
                return
            
            if not message.mentions:
                await message.channel.send("Please mention a user.")
                return

            target_id = message.mentions[0].id
            new_score = int(parts[-1])
            
            res = supabase.table('users').select('id').eq('discord_id', str(target_id)).execute()
            if res.data:
                uuid = res.data[0]['id']
                supabase.table('relationships').update({"trust_score": new_score}).eq('user_uuid', uuid).execute()
                await message.add_reaction("✅")
        except Exception as e:
            await message.channel.send(f"Error: {e}")
        return

    # Usage: !set_role @User enemy
    if message.content.startswith("!set_role"):
        if not message.author.guild_permissions.administrator:
             return
        try:
            parts = message.content.split()
            if len(parts) < 3:
                await message.channel.send("Usage: !set_role @User <role>")
                return
            
            if not message.mentions:
                await message.channel.send("Please mention a user.")
                return
            
            role = parts[-1].lower()
            target_id = message.mentions[0].id
            
            valid_roles = ['neutral', 'friend', 'enemy', 'annoying', 'baby', 'favorite']
            if role not in valid_roles:
                await message.channel.send(f"Invalid role. Choices: {', '.join(valid_roles)}")
                return

            res = supabase.table('users').select('id').eq('discord_id', str(target_id)).execute()
            if res.data:
                uuid = res.data[0]['id']
                supabase.table('relationships').update({"role": role}).eq('user_uuid', uuid).execute()
                await message.add_reaction("✅")
        except Exception as e:
            await message.channel.send(f"Error: {e}")
        return

    # 1. MENTION TRIGGER (100% response) OR DM (Direct Message)
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        if isinstance(message.channel, discord.DMChannel):
            print(f"DEBUG: DM received from {message.author.name}")
        await handle_bot_logic(message, is_ambient=False)
        return

    # 2. AMBIENT TRIGGER (Probability based)
    if not AMBIENT_ACTIVE: return

    roll = random.random()
    if roll < AMBIENT_CHANCE:
        # Check Cooldown
        channel_id = str(message.channel.id)
        now = time.time()
        if channel_id in last_ambient_response:
            if now - last_ambient_response[channel_id] < AMBIENT_COOLDOWN:
                # print(f"DEBUG: Ambient Cooldown Active for {message.channel.name} ({int(now - last_ambient_response[channel_id])}s / {AMBIENT_COOLDOWN}s)")
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
