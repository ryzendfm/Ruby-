-- 1. USERS: The master list
create table public.users (
  id uuid default gen_random_uuid() primary key,
  discord_id text not null unique, 
  username text,
  created_at timestamp with time zone default timezone('utc'::text, now())
);

-- 2. RELATIONSHIPS (The Emotional Core)
create table public.relationships (
  id uuid default gen_random_uuid() primary key,
  user_uuid uuid references public.users(id) on delete cascade not null,
  
  -- Stats
  affinity_score int default 0,  -- General liking (-100 to 100)
  trust_score int default 0,     -- How much she trusts them (0 to 100)
  jealousy_meter int default 0,  -- Temporary possessiveness (0 to 100)
  
  -- The Label
  role text default 'neutral',   -- 'baby', 'favorite', 'friend', 'neutral', 'annoying', 'enemy'
  
  -- Counters
  insults_count int default 0,
  compliments_count int default 0
);

-- 3. PERSONALITIES (The Speech Style)
create table public.personalities (
  id uuid default gen_random_uuid() primary key,
  user_uuid uuid references public.users(id) on delete cascade not null,
  vibe_summary text default 'New person.',
  nickname_preference text default null
);

-- 4. CONVOS (Memory)
create table public.convos (
  id uuid default gen_random_uuid() primary key,
  user_uuid uuid references public.users(id) on delete cascade not null,
  role text not null,
  content text not null,
  created_at timestamp with time zone default timezone('utc'::text, now())
);

-- 5. BOT_MOOD (Guild-wide Temper / Emotional State) -- STAGE 1
-- Tracks Ruby's current "mood" per-server, separate from her 1:1 relationship
-- with each individual user. This is what lets a bad interaction with someone
-- she dislikes bleed over into how she talks to EVERYONE in that server for a while.
create table public.bot_mood (
  id uuid default gen_random_uuid() primary key,
  guild_id text not null unique,
  current_mood text default 'neutral',   -- 'neutral', 'annoyed', 'angry', 'sulking', 'happy'
  intensity int default 0,                -- 0-100, decays over time / with calming
  triggered_by_uuid uuid references public.users(id) on delete set null,
  last_updated timestamp with time zone default timezone('utc'::text, now())
);
