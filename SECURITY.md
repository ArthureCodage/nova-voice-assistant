# Sécurité

## Signaler un problème

N’ouvre pas de ticket public contenant un jeton, une capture privée, une base mémoire ou toute
autre donnée personnelle. Utilise plutôt la fonction privée de signalement de vulnérabilité du
dépôt GitHub lorsqu’elle est disponible.

## Modèle de sécurité actuel

La V1 lance Codex avec une session éphémère et le bac à sable `read-only`. Elle ne propose pas de
mode général d’exécution de commandes. Les captures d’écran sont déclenchées explicitement et
supprimées après utilisation. Les souvenirs sont stockés localement dans un dossier exclu de Git.

Tout futur mode Action devra limiter les outils autorisés, présenter l’opération exacte et
obtenir une confirmation avant les suppressions, achats, messages, changements système ou accès
à des données sensibles.
