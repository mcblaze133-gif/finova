"""Local configuration. Never return configuration or credentials in API output."""
import os
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


def settings():
    return {**dotenv_values(ROOT / '.env', encoding='utf-8-sig'), **os.environ}


def model_settings():
    config = settings()
    if (config.get('GEMINI_FREE_TIER_CONFIRMED') or '').lower() != 'true':
        raise RuntimeError('Free-tier account not confirmed. Model calls disabled; verify billing is disabled and set GEMINI_FREE_TIER_CONFIRMED=true locally.')
    key = (config.get('GEMINI_API_KEY') or '').strip()
    if not key:
        raise RuntimeError('Gemini key is missing.')
    return key, config.get('GEMINI_MODEL', 'gemini-3.1-flash-lite')
