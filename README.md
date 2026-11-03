# MCP Zammad

Serveur MCP (**Model Context Protocol**) en **lecture seule** pour interroger un instance
Zammad (tickets, articles, utilisateurs, groupes). Conçu pour être utilisé avec les agents
de Mistral — notamment **Mistral Vibe Code** — ainsi qu'avec n'importe quel hôte MCP local
(opencode, Claude Desktop, etc.).

Deux transports sont pris en charge :

| Transport | Cas d'usage |
|---|---|
| `stdio` (défaut) | Hôte MCP local : opencode, tests, exécution directe dans un bac à sable |
| `streamable-http` | Exposition réseau (avec authentification par jeton) pour un connecteur MCP Mistral |

## Outils exposés

| Outil | Description |
|---|---|
| `search_tickets(query)` | Recherche de tickets avec la syntaxe de requête Zammad, ex. `group.id: 44 AND state.id: 2` |
| `get_ticket(ticket_id)` | Détail complet d'un ticket |
| `get_ticket_articles(ticket_id)` | Articles (messages/commentaires) d'un ticket |
| `get_user(user_id)` | Détail d'un utilisateur/agent |
| `search_users(query)` | Recherche d'utilisateurs, ex. `login: mainetti` |
| `list_groups()` | Liste des groupes (files de traitement) |
| `get_me()` | Profil de l'utilisateur authentifié (propriétaire du jeton) |

Toutes les requêtes envoyées à Zammad sont des `GET` en lecture seule : le serveur ne peut
jamais modifier ni supprimer de données.

## Installation

```bash
pip install .          # ou : pip install -e .
```

Dépendances : `mcp>=2.3.0`, `httpx`, `uvicorn` (installées automatiquement).

## Configuration

| Variable d'environnement | Requis | Défaut | Rôle |
|---|---|---|---|
| `ZAMMAD_TOKEN` | oui | — | Jeton d'API Zammad (Bearer) |
| `ZAMMAD_BASE_URL` | non | `https://support.cc.in2p3.fr` | URL de base de l'instance Zammad |
| `ZAMMAD_MCP_TRANSPORT` | non | `stdio` | `stdio` ou `streamable-http` |
| `ZAMMAD_MCP_HOST` | non | `127.0.0.1` | Adresse d'écoute en mode HTTP |
| `ZAMMAD_MCP_PORT` | non | `8000` | Port d'écoute en mode HTTP |
| `ZAMMAD_MCP_API_TOKEN` | oui en HTTP | — | Jeton Bearer que les clients MCP doivent présenter |

## Utilisation en local (stdio)

```bash
ZAMMAD_TOKEN=*** zammad-mcp
```

Exemple de configuration opencode :

```json
{
  "mcp": {
    "zammad": {
      "type": "local",
      "command": ["zammad-mcp"],
      "enabled": true,
      "environment": { "ZAMMAD_TOKEN": "***" }
    }
  }
}
```

## Utilisation en mode HTTP (streamable-http)

```bash
ZAMMAD_TOKEN=*** \
ZAMMAD_MCP_TRANSPORT=streamable-http \
ZAMMAD_MCP_PORT=8000 \
ZAMMAD_MCP_API_TOKEN=<secret-long-et-aleatoire> \
zammad-mcp
```

Le point de terminaison MCP est alors `http://<hote>:<port>/mcp` et une sonde de santé est
disponible sur `/healthz`.

**Important** : en mode HTTP, `ZAMMAD_MCP_API_TOKEN` est **obligatoire**. Le serveur refuse
de démarrer sans lui, car le point de terminaison expose vos données Zammad : toute requête
sans en-tête `Authorization: Bearer <token>` valide reçoit un `401`. Le mode est *stateless*
(aucune session collante requise), donc compatible avec n'importe quel reverse-proxy.

## Charger le serveur dans une autre instance de Mistral Vibe

Deux approches sont possibles, selon que vous voulez un usage ponctuel ou permanent.

### Option A — exécution directe dans la session (rapide, sans déploiement)

1. Téléversez les fichiers du dépôt dans la session Vibe (ou donnez l'URL du dépôt GitHub
   pour que l'agent le clone).
2. Demandez à l'agent, par exemple :

   > « Installe `zammad-mcp` (pip install .), puis démarre-le en stdio et vérifie
   > `get_me` avec ce jeton : *** »

3. L'agent installe le paquet, lance `zammad-mcp`, et interroge les outils via JSON-RPC
   sur l'entrée/sortie standard (initialisation, `tools/list`, `tools/call`).

Sécurité : le jeton transite dans la conversation. Utilisez de préférence un jeton
révocable, dédié et limité aux droits de lecture, et révoquez-le après usage.

### Option B — connecteur MCP Mistral permanent (déploiement)

Pour que le serveur soit disponible dans **toutes** vos sessions Vibe sans rien réinstaller :

1. Déployez le serveur en mode `streamable-http` sur un hôte qui peut atteindre votre
   instance Zammad (voir ci-dessus), derrière un reverse-proxy qui termine le TLS.
   Point de terminaison public attendu : `https://<votre-hote>/mcp`.
2. Enregistrez-le comme connecteur MCP personnalisé dans **Mistral Studio**
   (rubrique MCP Apps / connecteurs) :
   - URL : `https://<votre-hote>/mcp`
   - Authentification : `Bearer <ZAMMAD_MCP_API_TOKEN>`
3. Une fois le connecteur activé, les outils (`search_tickets`, `get_ticket`, …)
   apparaissent automatiquement dans vos sessions Vibe et peuvent être appelés
   directement, par exemple :

   > « Cherche dans Zammad les tickets du groupe 44 fermés ces 30 derniers jours. »

Dans une session Vibe, vous pouvez aussi demander à l'agent d'en lancer l'enregistrement :
il ouvre alors la page Studio correspondante où vous finalisez la connexion (le jeton ne
passe jamais par l'agent).

## Test rapide

```bash
# Vérifier l'installation et l'authentification Zammad
ZAMMAD_TOKEN=*** python -c "
from zammad_mcp.client import ZammadClient
print(ZammadClient('***').get_me()['login'])"

# En mode HTTP : sonde de santé et authentification
ZAMMAD_TOKEN=*** ZAMMAD_MCP_TRANSPORT=streamable-http ZAMMAD_MCP_API_TOKEN=secret zammad-mcp &
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/mcp -H 'Authorization: Bearer secret' \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Notes

- `list_groups` nécessite que l'utilisateur du jeton ait accès à la ressource
  `groups` de l'API Zammad (sinon l'API renvoie `403`).
- La recherche d'utilisateurs (`/users/search`) renvoie une liste simple alors que la
  recherche de tickets imbrique les résultats sous `assets` ; le serveur gère les deux
  formats.
- Testé avec `mcp` 2.3.0 contre une instance Zammad réelle (tous les outils, les deux
  transports, l'authentification 401/200).
