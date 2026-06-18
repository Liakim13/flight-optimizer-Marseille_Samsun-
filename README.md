# Optimiseur de vols MRS ↔ Samsun (via Istanbul)

Application Python qui scanne quotidiennement les prix Google Flights (via SerpApi) pour le trajet **Marseille (MRS) → Istanbul (IST/SAW) → Samsun (SZF)** avec Turkish Airlines et Pegasus, puis envoie un rapport HTML par e-mail.

**Exécution cloud** : le scan tourne sur **GitHub Actions** (cron 20h Paris), même si votre PC est éteint.

## Architecture

```
app_projet_avion/
├── .github/workflows/main.yml   # Cron + secrets + optimisations SerpApi
├── docs/GITHUB_SECRETS.md         # Guide configuration des secrets
├── main.py
├── src/optimizer.py             # SCAN_STEP_DAYS=7, cache, budget API
└── data/prices.db               # Persisté via cache GitHub Actions
```

## GitHub Actions — mise en route rapide

### 1. Pousser le code

```bash
git init && git add . && git commit -m "Optimiseur vols MRS-SZF"
git remote add origin https://github.com/VOTRE_USER/app_projet_avion.git
git push -u origin main
```

### 2. Configurer les GitHub Secrets

**Guide détaillé : [docs/GITHUB_SECRETS.md](docs/GITHUB_SECRETS.md)**

| Secret | Obligatoire | Description |
|--------|-------------|-------------|
| `SERPAPI_API_KEY` | Oui | Clé [SerpApi](https://serpapi.com/manage-api-key) |
| `SMTP_USER` | Oui | Adresse Gmail expéditrice |
| `SMTP_PASSWORD` | Oui | [Mot de passe d'application Gmail](https://myaccount.google.com/apppasswords) |
| `EMAIL_TO` | Oui | Adresse de réception du rapport |
| `EMAIL_FROM` | Non | Défaut = `SMTP_USER` |

**Chemin GitHub** : Settings → Secrets and variables → Actions → New repository secret

### 3. Tester

Actions → **Scan vols MRS-SZF** → **Run workflow**

### 4. Cron 20h00 Paris

GitHub Actions utilise **UTC** :

| Saison | Cron dans `main.yml` |
|--------|----------------------|
| Hiver (CET) | `'0 19 * * *'` |
| Été (CEST) | `'0 18 * * *'` |

---

## Optimisation SerpApi (`SCAN_STEP_DAYS=7`)

Pour rester dans les limites du plan SerpApi :

| Paramètre | Défaut | Effet |
|-----------|--------|-------|
| `SCAN_STEP_DAYS=7` | 7 | 1 date / semaine (~13 ancres sur 3 mois au lieu de ~90) |
| `MAX_OPTIONS_PER_SEARCH=1` | 1 | Analyse uniquement le meilleur vol par recherche |
| `API_CACHE_HOURS=168` | 7 jours | Réutilise les réponses déjà obtenues |
| Pré-validation aller | — | Évite l'appel retour si l'aller est invalide |
| `MAX_API_CALLS_PER_RUN=200` | 200 | Plafond de sécurité par exécution |

**Consommation estimée :**

- 1er run (cache vide) : ~150–200 appels
- Runs suivants : ~20–40 appels (seules les nouvelles dates sont interrogées)

Le cache SQLite (`data/`) est restauré à chaque run via `actions/cache`.

---

## Développement local

```bash
pip install -r requirements.txt
copy .env.example .env
python main.py --dry-run
```

## Rapport e-mail

- **Opportunité du jour** (baisse ≥ 5 % ou ≥ 30 € vs veille)
- Top 3 combinaisons par profil (2, 3 et 4 semaines)
- Prix, compagnies, horaires, durée totale incluant escales Istanbul
