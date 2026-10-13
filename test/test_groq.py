#!/usr/bin/env python3
"""
Test script to verify connectivity to Groq API and test Groq models.
Checks API key authentication, model listing, and performs test completions
on models used by the Ruby bot.
"""

import sys
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded from project root if running from inside /test or workspace root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
load_dotenv()  # fallback to standard dotenv discovery

import os
from groq import Groq, AuthenticationError, APIConnectionError, RateLimitError, APIError

# Default models used in ruby_bot.py
BOT_MODELS = [
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b"
]

def check_groq_connectivity(custom_models=None):
    api_key = os.getenv("GROQ_API_KEY")

    print("=" * 60)
    print("           GROQ API & MODELS CONNECTIVITY TEST")
    print("=" * 60)

    # 1. Check API Key presence
    if not api_key or not api_key.strip():
        print("\n[-] FAILED: GROQ_API_KEY environment variable is missing or empty.")
        print("    Please set GROQ_API_KEY in your .env file or environment.")
        print(f"    Expected .env location: {PROJECT_ROOT / '.env'}\n")
        return False

    masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
    print(f"\n[+] GROQ_API_KEY detected: {masked_key}")

    # 2. Initialize Groq client
    try:
        client = Groq(api_key=api_key)
    except Exception as e:
        print(f"[-] FAILED: Could not initialize Groq client: {e}")
        return False

    # 3. Test API connectivity and fetch available models
    print("\n--- 1. Testing API Authentication & Model Listing ---")
    start_time = time.time()
    try:
        models_response = client.models.list()
        elapsed_ms = (time.time() - start_time) * 1000
        available_model_ids = {m.id for m in models_response.data}
        print(f"[+] Successfully connected to Groq API ({elapsed_ms:.1f}ms)")
        print(f"[+] Total models accessible on your account: {len(available_model_ids)}")
        print(f"    Available models: {', '.join(sorted(available_model_ids))}")
    except AuthenticationError:
        print("[-] FAILED: AuthenticationError - Provided GROQ_API_KEY is invalid or expired.")
        return False
    except APIConnectionError as e:
        print(f"[-] FAILED: APIConnectionError - Cannot connect to Groq endpoints. Network issue: {e}")
        return False
    except RateLimitError as e:
        print(f"[-] FAILED: RateLimitError - Rate limit reached: {e}")
        return False
    except APIError as e:
        print(f"[-] FAILED: APIError from Groq: {e}")
        return False
    except Exception as e:
        print(f"[-] FAILED: Unexpected error while connecting: {e}")
        return False

    # 4. Test inference connectivity on models
    models_to_test = custom_models if custom_models else BOT_MODELS
    print(f"\n--- 2. Testing Model Inference ({len(models_to_test)} model(s)) ---")

    test_prompt = "Hello! Please respond with only the word 'PONG' to verify model connectivity."
    all_succeeded = True

    for model_name in models_to_test:
        print(f"\n>> Testing model: '{model_name}'")
        if model_name not in available_model_ids:
            print(f"   [!] WARNING: Model '{model_name}' was not found in the listed accessible models for this key.")

        start_model_time = time.time()
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a test agent. Keep answers extremely brief."},
                    {"role": "user", "content": test_prompt}
                ],
                model=model_name,
                max_tokens=20,
                temperature=0.0
            )
            model_elapsed_ms = (time.time() - start_model_time) * 1000
            reply_text = response.choices[0].message.content.strip().replace("\n", " ")
            usage = response.usage

            print(f"   [+] Status: OK ({model_elapsed_ms:.1f}ms)")
            print(f"   [+] Response: \"{reply_text}\"")
            if usage:
                print(f"   [+] Tokens used: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}, total={usage.total_tokens}")

        except RateLimitError as e:
            print(f"   [-] FAILED: Rate limit exceeded: {e}")
            all_succeeded = False
        except APIError as e:
            print(f"   [-] FAILED: API Error for model '{model_name}': {e}")
            all_succeeded = False
        except Exception as e:
            print(f"   [-] FAILED: Unexpected error: {e}")
            all_succeeded = False

    print("\n" + "=" * 60)
    if all_succeeded:
        print("   RESULT: ALL GROQ MODEL CONNECTIVITY TESTS PASSED! [SUCCESS]")
    else:
        print("   RESULT: ONE OR MORE GROQ MODEL TESTS FAILED! [FAILURE]")
    print("=" * 60 + "\n")

    return all_succeeded

def main():
    parser = argparse.ArgumentParser(description="Verify connectivity to Groq API and test models.")
    parser.add_argument(
        "--model",
        "-m",
        action="append",
        dest="models",
        help="Specific Groq model to test (can be specified multiple times). Defaults to bot models."
    )
    args = parser.parse_args()

    success = check_groq_connectivity(custom_models=args.models)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
