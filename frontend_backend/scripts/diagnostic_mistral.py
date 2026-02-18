#!/usr/bin/env python3
"""
Script de diagnostic pour vérifier la configuration de l'IA Mistral
"""
import os
import sys
from pathlib import Path

# Ajouter le dossier parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

def check_env_file():
    """Vérifie si le fichier .env existe"""
    env_path = Path(__file__).parent.parent / '.env'
    print("=" * 60)
    print("1. Vérification du fichier .env")
    print("=" * 60)
    
    if env_path.exists():
        print(f"✅ Fichier .env trouvé : {env_path}")
        return True
    else:
        print(f"❌ Fichier .env non trouvé : {env_path}")
        print("   Créez le fichier à partir de .env.example")
        return False

def check_api_key():
    """Vérifie si la clé API est configurée"""
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n" + "=" * 60)
    print("2. Vérification de la clé API Mistral")
    print("=" * 60)
    
    api_key = os.getenv('MISTRAL_API_KEY')
    
    if not api_key:
        print("❌ MISTRAL_API_KEY n'est pas définie")
        print("   Ajoutez votre clé dans le fichier .env")
        return False
    elif api_key.strip() == "":
        print("❌ MISTRAL_API_KEY est vide")
        print("   Ajoutez votre clé dans le fichier .env")
        return False
    else:
        # Masquer la clé sauf les premiers et derniers caractères
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        print(f"✅ Clé API trouvée : {masked_key}")
        return True

def check_mistral_module():
    """Vérifie si le module mistralai est installé"""
    print("\n" + "=" * 60)
    print("3. Vérification du module mistralai")
    print("=" * 60)
    
    try:
        import mistralai
        print(f"✅ Module mistralai installé (version {mistralai.__version__ if hasattr(mistralai, '__version__') else 'inconnue'})")
        return True
    except ImportError:
        print("❌ Module mistralai non installé")
        print("   Installez-le avec : pip install mistralai>=0.0.7")
        return False

def test_api_connection():
    """Teste la connexion à l'API Mistral"""
    print("\n" + "=" * 60)
    print("4. Test de connexion à l'API Mistral")
    print("=" * 60)
    
    try:
        from mistralai import Mistral
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('MISTRAL_API_KEY')
        if not api_key:
            print("❌ Impossible de tester sans clé API")
            return False
        
        print("   Envoi d'une requête test...")
        client = Mistral(api_key=api_key)
        
        chat_response = client.chat.complete(
            model="mistral-small-2503",
            messages=[{"role": "user", "content": "Bonjour"}],
            max_tokens=10
        )
        
        response = chat_response.choices[0].message.content
        print(f"✅ Connexion réussie ! Réponse : '{response[:50]}...'")
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la connexion : {e}")
        return False

def check_ai_summary_import():
    """Vérifie si ai_summary.py peut être importé"""
    print("\n" + "=" * 60)
    print("5. Vérification du module ai_summary")
    print("=" * 60)
    
    try:
        from ai_summary import generate_medicine_summary, MISTRAL_API_KEY, MISTRAL_AVAILABLE
        
        print(f"✅ Module ai_summary importé")
        print(f"   - MISTRAL_AVAILABLE : {MISTRAL_AVAILABLE}")
        print(f"   - Clé API configurée : {'Oui' if MISTRAL_API_KEY else 'Non'}")
        return True
    except Exception as e:
        print(f"❌ Erreur d'importation : {e}")
        return False

def main():
    """Exécute tous les diagnostics"""
    print("\n" + "=" * 60)
    print("DIAGNOSTIC DE CONFIGURATION MISTRAL AI")
    print("=" * 60 + "\n")
    
    results = []
    
    # Exécuter tous les tests
    results.append(("Fichier .env", check_env_file()))
    results.append(("Clé API", check_api_key()))
    results.append(("Module mistralai", check_mistral_module()))
    results.append(("Module ai_summary", check_ai_summary_import()))
    results.append(("Connexion API", test_api_connection()))
    
    # Résumé
    print("\n" + "=" * 60)
    print("RÉSUMÉ")
    print("=" * 60)
    
    all_ok = all(result[1] for result in results)
    
    for name, status in results:
        symbol = "✅" if status else "❌"
        print(f"{symbol} {name}")
    
    print("\n" + "=" * 60)
    
    if all_ok:
        print("🎉 TOUT EST CONFIGURÉ CORRECTEMENT !")
        print("=" * 60)
        print("\nVous pouvez maintenant :")
        print("1. Lancer votre application Flask")
        print("2. Naviguer vers une page de médicament")
        print("3. Le résumé IA devrait s'afficher automatiquement")
    else:
        print("⚠️  CONFIGURATION INCOMPLÈTE")
        print("=" * 60)
        print("\nÉtapes à suivre :")
        print("1. Consultez le fichier README_IA_MISTRAL.md")
        print("2. Obtenez une clé API sur https://console.mistral.ai/")
        print("3. Ajoutez-la dans frontend_backend/.env")
        print("4. Relancez ce diagnostic")
    
    print()
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
