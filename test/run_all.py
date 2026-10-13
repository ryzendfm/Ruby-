#!/usr/bin/env python3
"""
Convenience test runner to execute both Groq and Discord connectivity tests.
"""

import sys
import subprocess
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent

def run_test(script_name: str) -> bool:
    script_path = CURRENT_DIR / script_name
    print(f"\n>>> Running {script_name}...")
    res = subprocess.run([sys.executable, str(script_path)])
    return res.returncode == 0

def main():
    print("=" * 60)
    print("         RUNNING ALL CONNECTIVITY TESTS")
    print("=" * 60)

    groq_ok = run_test("test_groq.py")
    discord_ok = run_test("test_discord.py")

    print("\n" + "=" * 60)
    print("                  SUMMARY")
    print("=" * 60)
    print(f" Groq Connectivity   : {'[PASSED]' if groq_ok else '[FAILED]'}")
    print(f" Discord Connectivity: {'[PASSED]' if discord_ok else '[FAILED]'}")
    print("=" * 60)

    all_passed = groq_ok and discord_ok
    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    main()
