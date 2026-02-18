#!/usr/bin/env python3
"""
Script d'aide pour ajouter de nouvelles traductions
Usage: python add_translation.py <key> <fr> <en> <ar>
Exemple: python add_translation.py "new_feature" "Nouvelle fonctionnalité" "New feature" "ميزة جديدة"
"""

import sys
import os

def add_translation(key, fr_text, en_text, ar_text):
    """Ajoute une nouvelle traduction dans les 3 fichiers .po"""
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    translations_path = os.path.join(base_path, 'translations')
    
    languages = {
        'fr': fr_text,
        'en': en_text,
        'ar': ar_text
    }
    
    new_entry = f'\nmsgid "{key}"\nmsgstr "{{}}"\n'
    
    for lang, text in languages.items():
        po_file = os.path.join(translations_path, lang, 'LC_MESSAGES', 'messages.po')
        
        if not os.path.exists(po_file):
            print(f"❌ Fichier non trouvé: {po_file}")
            continue
        
        # Vérifier si la clé existe déjà
        with open(po_file, 'r', encoding='utf-8') as f:
            content = f.read()
            if f'msgid "{key}"' in content:
                print(f"⚠️  La clé '{key}' existe déjà dans {lang}")
                continue
        
        # Ajouter la nouvelle entrée
        with open(po_file, 'a', encoding='utf-8') as f:
            f.write(new_entry.format(text))
        
        print(f"✅ Ajouté dans {lang}: {key} = {text}")
    
    print("\n📝 N'oubliez pas de compiler les traductions:")
    print("   pybabel compile -d translations -l fr")
    print("   pybabel compile -d translations -l en")
    print("   pybabel compile -d translations -l ar")

if __name__ == '__main__':
    if len(sys.argv) != 5:
        print("Usage: python add_translation.py <key> <fr> <en> <ar>")
        print('Exemple: python add_translation.py "new_feature" "Nouvelle fonctionnalité" "New feature" "ميزة جديدة"')
        sys.exit(1)
    
    key = sys.argv[1]
    fr_text = sys.argv[2]
    en_text = sys.argv[3]
    ar_text = sys.argv[4]
    
    add_translation(key, fr_text, en_text, ar_text)
