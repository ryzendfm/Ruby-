#!/usr/bin/env python3
"""
Test script to verify connectivity to Discord API and Gateway.
Checks DISCORD_TOKEN validity via REST API, tests WebSocket gateway
connection, validates intents, reports latency, and checks guild status.
"""

import sys
import time
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded from project root if running from inside /test or workspace root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
load_dotenv()  # fallback to standard dotenv discovery

import os
import requests
import discord

GATEWAY_TIMEOUT_SECONDS = 15

def verify_discord_rest(token: str) -> dict | None:
    """Tests Discord HTTP REST API using the Bot token."""
    print("\n--- 1. Testing Discord REST API Authentication ---")
    url = "https://discord.com/api/v10/users/@me"
    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "RubyBotConnectivityTest/1.0"
    }

    start_time = time.time()
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        elapsed_ms = (time.time() - start_time) * 1000
    except requests.exceptions.RequestException as e:
        print(f"[-] FAILED: Could not reach Discord REST endpoint: {e}")
        return None

    if resp.status_code == 200:
        data = resp.json()
        print(f"[+] REST API Connection Successful ({elapsed_ms:.1f}ms)")
        print(f"[+] Bot Username: {data.get('username')}#{data.get('discriminator', '0')}")
        print(f"[+] Bot User ID : {data.get('id')}")
        print(f"[+] Bot Verified: {data.get('verified', False)}")
        return data
    elif resp.status_code == 401:
        print("[-] FAILED (401 Unauthorized): Invalid DISCORD_TOKEN provided.")
        print("    Please double-check your bot token from the Discord Developer Portal.")
        return None
    elif resp.status_code == 403:
        print(f"[-] FAILED (403 Forbidden): Access denied. Message: {resp.text}")
        return None
    else:
        print(f"[-] FAILED: Unexpected status code {resp.status_code}: {resp.text}")
        return None

async def verify_discord_gateway(token: str) -> bool:
    """Connects to the Discord Gateway WebSocket and checks latency & intents."""
    print("\n--- 2. Testing Discord Gateway WebSocket Connection ---")
    intents = discord.Intents.default()
    intents.message_content = True  # Required by Ruby bot

    client = discord.Client(intents=intents)
    connected_event = asyncio.Event()
    test_result = {"success": False, "error": None}

    @client.event
    async def on_ready():
        try:
            latency_ms = client.latency * 1000 if client.latency else 0.0
            print(f"[+] Successfully connected to Discord Gateway!")
            print(f"[+] Logged in as : {client.user.name} (ID: {client.user.id})")
            print(f"[+] Gateway Ping : {latency_ms:.1f} ms")
            print(f"[+] Guilds Count : {len(client.guilds)}")

            if client.guilds:
                print("    Connected Guilds (Servers):")
                for guild in client.guilds[:5]:
                    print(f"    - {guild.name} (ID: {guild.id}, Members: {guild.member_count})")
                if len(client.guilds) > 5:
                    print(f"    - ... and {len(client.guilds) - 5} more server(s)")
            else:
                print("    [!] Bot is currently not in any Discord servers.")

            # Check if Message Content Intent is active
            if client.intents.message_content:
                print("[+] Intent Check : Message Content intent is active and enabled.")
            else:
                print("[-] Intent Check : Message Content intent is NOT active.")

            test_result["success"] = True
        except Exception as e:
            test_result["error"] = e
        finally:
            connected_event.set()
            await client.close()

    try:
        # Start the client task
        login_task = asyncio.create_task(client.start(token))

        # Wait for on_ready or timeout
        await asyncio.wait_for(connected_event.wait(), timeout=GATEWAY_TIMEOUT_SECONDS)

        # Ensure login task finishes closing cleanly
        try:
            await login_task
        except (asyncio.CancelledError, Exception):
            pass

        # Give aiohttp session connectors time to close cleanly
        await asyncio.sleep(0.5)

        return test_result["success"]

    except asyncio.TimeoutError:
        print(f"[-] FAILED: Gateway connection timed out after {GATEWAY_TIMEOUT_SECONDS}s.")
        print("    Check your network/firewall or Discord status.")
        await client.close()
        return False
    except discord.errors.PrivilegedIntentsRequired:
        print("[-] FAILED: PrivilegedIntentsRequired error!")
        print("    The bot requires 'Message Content Intent', but it is not enabled in the")
        print("    Discord Developer Portal -> Your App -> Bot -> Privileged Gateway Intents.")
        await client.close()
        return False
    except discord.errors.LoginFailure as e:
        print(f"[-] FAILED: Discord LoginFailure: {e}")
        await client.close()
        return False
    except Exception as e:
        print(f"[-] FAILED: Gateway error: {e}")
        await client.close()
        return False

def check_discord_connectivity():
    token = os.getenv("DISCORD_TOKEN")

    print("=" * 60)
    print("              DISCORD CONNECTIVITY TEST")
    print("=" * 60)

    # 1. Check Token presence
    if not token or not token.strip():
        print("\n[-] FAILED: DISCORD_TOKEN environment variable is missing or empty.")
        print("    Please set DISCORD_TOKEN in your .env file or environment.")
        print(f"    Expected .env location: {PROJECT_ROOT / '.env'}\n")
        return False

    masked_token = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
    print(f"\n[+] DISCORD_TOKEN detected: {masked_token}")

    # 2. Stage 1: REST API
    rest_data = verify_discord_rest(token)
    if not rest_data:
        print("\n" + "=" * 60)
        print("   RESULT: DISCORD REST AUTHENTICATION FAILED! [FAILURE]")
        print("=" * 60 + "\n")
        return False

    # 3. Stage 2: Gateway WebSocket
    try:
        gateway_ok = asyncio.run(verify_discord_gateway(token))
    except Exception as e:
        print(f"[-] Error running asyncio gateway test: {e}")
        gateway_ok = False

    print("\n" + "=" * 60)
    if gateway_ok:
        print("   RESULT: ALL DISCORD CONNECTIVITY TESTS PASSED! [SUCCESS]")
    else:
        print("   RESULT: DISCORD GATEWAY CONNECTION TEST FAILED! [FAILURE]")
    print("=" * 60 + "\n")

    return gateway_ok

def main():
    success = check_discord_connectivity()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
