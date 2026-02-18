#!/usr/bin/env python3
"""Test rapide de la connexion Mistral API"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Charger le .env depuis la racine du projet
env_path = Path(__file__).parent.parent.parent / '.env'
print(f"Chargement du fichier .env depuis : {env_path}")
print(f"Fichier existe : {env_path.exists()}")

load_dotenv(dotenv_path=env_path)

# Obtenir la clé API
api_key = os.getenv('MISTRAL_API_KEY')

if not api_key:
    print("❌ ERREUR : MISTRAL_API_KEY non trouvée dans le fichier .env")
    sys.exit(1)

print(f"✅ Clé API trouvée : {api_key[:8]}...{api_key[-4:]}")

try:
    from mistralai import Mistral
    print("✅ Module mistralai importé avec succès")
    
    # Tester la connexion
    print("\nTest de connexion à l'API Mistral...")
    client = Mistral(api_key=api_key)
    
    response = client.chat.complete(
        model="mistral-small-2503",
        messages=[{"role": "user", "content": "Dis bonjour en une phrase"}],
        max_tokens=50
    )
    
    print(f"✅ Connexion réussie !")
    print(f"Réponse : {response.choices[0].message.content}")
    print("\n🎉 La configuration Mistral est opérationnelle !")
    
except Exception as e:
    print(f"❌ Erreur : {e}")
    sys.exit(1)
