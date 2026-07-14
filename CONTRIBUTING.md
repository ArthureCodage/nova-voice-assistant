# Contribuer à Nova

Merci de vouloir améliorer Nova.

## Principes

- Préserver la vie privée par défaut.
- Demander une confirmation avant toute action sensible.
- Garder les fonctions vocales utilisables localement.
- Ne jamais ajouter de secret, de base SQLite, de capture d’écran ou de modèle binaire au dépôt.
- Maintenir une expérience Windows simple pour les personnes non techniques.

## Avant une proposition

1. Crée une branche courte et descriptive.
2. Explique le problème et le comportement attendu.
3. Vérifie la syntaxe avec `python -m py_compile assistant.py`.
4. Teste manuellement les fonctions Windows touchées.
5. Décris les conséquences éventuelles sur la confidentialité et la sécurité.

Les changements donnant davantage de contrôle du PC à Nova doivent inclure des garde-fous et
une confirmation explicite de l’utilisateur.
