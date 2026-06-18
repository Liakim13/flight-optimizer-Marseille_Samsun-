# Configuration des GitHub Secrets

Ce guide explique comment stocker de manière sécurisée vos identifiants SerpApi et Gmail pour le workflow `.github/workflows/main.yml`.

Les secrets **ne sont jamais** écrits dans le code, le dépôt Git ou les logs GitHub.

---

## Étape 1 — Ouvrir la page des secrets

1. Allez sur votre dépôt GitHub (ex. `https://github.com/VOTRE_USER/app_projet_avion`)
2. Cliquez sur **Settings** (Paramètres)
3. Dans le menu gauche : **Secrets and variables** → **Actions**
4. Cliquez sur **New repository secret**

---

## Étape 2 — Créer chaque secret

Créez **un secret par ligne** du tableau ci-dessous.

| Nom du secret | Obligatoire | Où le trouver | Exemple |
|---------------|-------------|---------------|---------|
| `SERPAPI_API_KEY` | **Oui** | [serpapi.com/manage-api-key](https://serpapi.com/manage-api-key) | `a1b2c3d4e5f6...` |
| `SMTP_USER` | **Oui** | Votre adresse Gmail | `vous@gmail.com` |
| `SMTP_PASSWORD` | **Oui** | Mot de passe d'application Gmail (voir ci-dessous) | `abcdefghijklmnop` |
| `EMAIL_TO` | **Oui** | Adresse qui reçoit le rapport quotidien | `vous@gmail.com` |
| `EMAIL_FROM` | Non | Expéditeur affiché (défaut = `SMTP_USER`) | `vous@gmail.com` |

### Créer le mot de passe d'application Gmail

1. Activez la [validation en 2 étapes](https://myaccount.google.com/signinoptions/two-step-verification) sur votre compte Google
2. Ouvrez [Mots de passe des applications](https://myaccount.google.com/apppasswords)
3. Créez un mot de passe pour **Autre (nom personnalisé)** → `Flight Optimizer`
4. Copiez les **16 caractères** (sans espaces) dans le secret `SMTP_PASSWORD`

### Obtenir la clé SerpApi

1. Créez un compte sur [serpapi.com](https://serpapi.com/)
2. Copiez votre clé depuis [serpapi.com/manage-api-key](https://serpapi.com/manage-api-key)
3. Collez-la dans le secret `SERPAPI_API_KEY`

---

## Étape 3 — Vérifier la configuration

1. Onglet **Actions** → workflow **Scan vols MRS-SZF**
2. **Run workflow** → **Run workflow**
3. Vérifiez que l'étape *Vérifier les secrets obligatoires* passe au vert
4. Consultez votre boîte mail

En cas d'échec, téléchargez l'artifact `rapport-vols-*` (HTML + logs).

---

## Paramètres non sensibles (dans le workflow, pas en secrets)

Ces variables sont définies dans `.github/workflows/main.yml` et peuvent être modifiées directement dans le fichier :

| Variable | Valeur par défaut | Rôle |
|----------|-------------------|------|
| `SCAN_STEP_DAYS` | `7` | 1 date scannée par semaine (réduit les appels SerpApi) |
| `MAX_OPTIONS_PER_SEARCH` | `1` | 1 seul vol analysé par recherche |
| `API_CACHE_HOURS` | `168` | Cache 7 jours (évite les requêtes répétées) |
| `MAX_API_CALLS_PER_RUN` | `200` | Plafond de sécurité par exécution |
| `SCAN_MONTHS` | `3` | Fenêtre glissante de 3 mois |
| `DATE_OFFSET_DAYS` | `2` | Flexibilité ±2 jours sur le départ |

---

## Consommation SerpApi estimée

| Situation | Appels approximatifs |
|-----------|---------------------|
| **1er run** (cache vide) | ~150–200 (plafonné) |
| **Runs suivants** (cache actif) | ~20–40 (nouvelles dates uniquement) |

Avec `SCAN_STEP_DAYS=7`, le scan couvre ~13 dates de référence × 3 profils × 5 décalages = **~195 combinaisons**, mais le cache SQLite persisté entre les runs évite de re-interroger SerpApi pour les mêmes dates.

---

## Sécurité

- Ne commitez **jamais** de fichier `.env` contenant des clés réelles
- Ne partagez pas vos secrets dans les issues ou pull requests
- Pour rotation : modifiez le secret dans GitHub → le prochain run utilisera la nouvelle valeur
- Révoquez un mot de passe d'application Gmail compromis depuis [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
