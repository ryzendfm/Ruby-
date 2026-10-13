# 💎 Ruby — Discord AI Chatbot

Ruby is an intelligent, emotionally-driven Discord companion chatbot powered by **Groq LLMs** and **Supabase**. Unlike static chatbots, Ruby possesses persistent memory, evolving interpersonal relationships, a server-wide mood/temper system, multimodal image perception, and an ambient conversation presence.

---

## ✨ Key Features

- **🧠 Dual-Model & Multimodal Intelligence (Groq)**:
  - **Reasoning & Chat:** Powered by `qwen/qwen3.8-27b` for rich, nuanced, and contextual conversations.
  - **Emotional & Vibe Analysis:** Powered by `openai/gpt-oss-20b` (JSON mode) to continuously evaluate sentiment, affinity, trust, and user vibes in the background.
  - **Vision / Image Understanding:** Automatically switches to `meta-llama/llama-4-scout-17b-16e-instruct` when users attach images (PNG, JPG, JPEG, GIF, WebP).
- **❤️ Relationship & Memory System (Supabase)**:
  - Tracks 1-on-1 dynamic stats for each user: **Affinity** (-100 to 100), **Trust** (0 to 100), **Jealousy** (0 to 100), insults, and compliments.
  - Assigns dynamic roles: `baby` (supreme role), `favorite`, `friend`, `neutral`, `annoying`, and `enemy`.
  - Recognizes user nickname preferences on the fly (`[SET_NAME: ...]`).
- **💢 Guild-Wide Mood & Temper (Stage 1)**:
  - Server-level emotional state (`bot_mood`): `neutral`, `annoyed`, `angry`, `sulking`, or `happy`.
  - Bad interactions with enemies bleed over into how she interacts with the server, while interactions with favorites soothe her temper.
  - Passive time-based mood decay slowly restores calm over time.
- **⏰ Temporal Awareness**:
  - Calculates fuzzy time differences since you last spoke (IST timezone).
  - Teases fast replies or welcomes back users who haven't spoken in days.
- **💬 Ambient Chatting**:
  - Can occasionally jump into ongoing channel conversations without being explicitly tagged (`!ambient on/off`), guarded by cooldowns and history checks.
- **🧪 Automated Sanity & Health Testing**:
  - Built-in test suite for Groq API, Discord Gateway, REST APIs, and Supabase connectivity with GitHub Actions integration.

---

## 🛠️ Tech Stack & Architecture

- **Language:** Python 3.11+
- **Discord Framework:** `discord.py`
- **Database:** Supabase (PostgreSQL)
- **AI Inference:** Groq Cloud API
- **Deployment:** Heroku / Railway / Docker / Micro VM via `Procfile` (`worker: python ruby_bot.py`)

---

## 📂 Project Structure

```
├── .github/
│   └── workflows/
│       ├── pr_test_all.yml     # Automated PR connectivity & sanity check
│       ├── test_discord.yml    # Manual Discord REST & Gateway check
│       └── test_groq.yml       # Manual Groq model inference check
├── test/
│   ├── run_all.py              # Master test runner (subprocesses)
│   ├── test_discord.py         # Discord REST + WebSocket gateway probe
│   └── test_groq.py            # Groq authentication & ping-pong inference probe
├── Procfile                    # Worker process definition
├── requirements.txt            # Python dependencies
├── ruby_bot.py                 # Core bot application & event loop
├── schema.sql                  # Supabase database schema
├── verify_db.py                # Database verification utility
└── .env                        # Local environment configuration
```

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.11 or newer
- A [Discord Developer Application](https://discord.com/developers/applications) with **Message Content Intent** enabled
- A [Groq Cloud](https://console.groq.com/) API Key
- A [Supabase](https://supabase.com/) project

### 2. Database Setup

Execute the SQL script in [schema.sql](schema.sql) in your Supabase SQL Editor to initialize the required tables:
- `users` — Discord ID mapping and user registration
- `relationships` — User affinity, trust, jealousy, and relationship roles
- `personalities` — User vibe summaries and nickname preferences
- `convos` — Chat logs and contextual memory
- `bot_mood` — Guild-level temper and intensity tracking

### 3. Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/ryzendfm/Ruby-.git
cd Ruby-
pip install -r requirements.txt
```

### 4. Configuration

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_discord_bot_token_here
GROQ_API_KEY=your_groq_api_key_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_or_service_key
```

### 5. Run Sanity Checks

Before starting the bot, verify all API connections and credentials:

```bash
# Run all connectivity and sanity tests
python test/run_all.py

# Or run individual checks:
python test/test_groq.py
python test/test_discord.py
python verify_db.py
```

### 6. Start the Bot

```bash
python ruby_bot.py
```

---

## 🤖 Bot Commands

| Command | Permission | Description |
|---|---|---|
| `!stats [@user]` | Everyone | View your or mentioned user's relationship role, affinity, trust, and jealousy meters. |
| `!mood` | Admin | Check Ruby's current guild-wide mood state and intensity score (0-100). |
| `!mood reset` | Admin | Manually reset Ruby's guild-wide temper back to neutral. |
| `!ambient <on\|off>` | Admin | Toggle or inspect ambient random response mode for the server. |
| `!set_role @user <role>` | Admin | Manually set user relationship role (`neutral`, `friend`, `enemy`, `annoying`, `favorite`, `baby`). |
| `!set_affinity @user <score>` | Admin | Adjust affinity score (-100 to 100). |
| `!set_trust @user <score>` | Admin | Adjust trust score (0 to 100). |

---

## 🔒 GitHub Actions Secrets Setup

If running CI/CD workflows via GitHub Actions:
1. Navigate to **Settings** -> **Secrets and variables** -> **Actions** -> **Repository secrets**.
2. Add the following repository secrets:
   - `DISCORD_TOKEN`
   - `GROQ_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`

---

## 📄 License

This project is licensed under the MIT License.
