#!/usr/bin/env python3
"""Vérifier si la clé API Mistral est chargée dans ai_summary.py"""
import sys
from pathlib import Path

# Ajouter le chemin
sys.path.insert(0, str(Path(__file__).parent.parent))

print("Test de chargement de la clé API Mistral...")
print()

# Importer ai_summary
from ai_summary import MISTRAL_API_KEY, MISTRAL_AVAILABLE

print(f"MISTRAL_AVAILABLE: {MISTRAL_AVAILABLE}")
print(f"MISTRAL_API_KEY exists: {MISTRAL_API_KEY is not None}")

if MISTRAL_API_KEY:
    print(f"Clé API: {MISTRAL_API_KEY[:8]}...{MISTRAL_API_KEY[-4:]}")
    print("✅ La clé API est chargée correctement !")
else:
    print("❌ La clé API n'est PAS chargée")
    print()
    print("Vérifications:")
    
    # Vérifier le fichier .env
    env_path = Path(__file__).parent.parent.parent / '.env'
    print(f"Fichier .env: {env_path}")
    print(f"Existe: {env_path.exists()}")
    
    if env_path.exists():
        print()
        print("Contenu du .env (MISTRAL_API_KEY uniquement):")
        with open(env_path, 'r') as f:
            for line in f:
                if 'MISTRAL_API_KEY' in line:
                    print(f"  {line.strip()}")
