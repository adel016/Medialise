#!/usr/bin/env python3
"""
Script de lancement de Flask avec gestion des erreurs PyTorch/Sentence Transformers
"""
import sys
import os

# Ajouter le chemin du frontend_backend au PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("Démarrage de l'application Flask...")
print("=" * 60)

try:
    from app import app
    print("✅ Application chargée avec succès")
    print()
    print("🌐 Accédez à l'application sur : http://localhost:5000")
    print("🛑 Pour arrêter : Ctrl+C")
    print("=" * 60)
    print()
    
    app.run(debug=True, host='0.0.0.0', port=5000)
    
except KeyboardInterrupt:
    print("\n👋 Application arrêtée")
except Exception as e:
    print(f"❌ Erreur lors du démarrage : {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
