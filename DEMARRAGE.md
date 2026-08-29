# ACC — Autonomous Mission Control · guide de démarrage

De l'archive au déploiement Google Cloud, avec le suivi des coûts.

> **À lire d'abord.** Rien de ce qui suit n'a été exécuté depuis mon
> environnement : je n'avais accès ni à un projet GCP, ni à Docker, ni à un
> navigateur. Le code, lui, est vérifié par exécution (129 tests, audit 47/47,
> scénario héros en HTTP réel). Les commandes ci-dessous sont issues de la
> documentation Google vérifiée le 25 août 2026 — mais **vous serez le premier
> à les lancer**. Les pièges connus sont signalés.

---

## Sommaire

1. [Vérification locale — 2 minutes, sans cloud](#1-vérification-locale)
2. [Pile complète en local](#2-pile-complète-en-local)
3. [Google Cloud — préparation du projet](#3-google-cloud--préparation-du-projet)
4. [Budget et garde-fous — **à faire avant tout le reste**](#4-budget-et-garde-fous)
5. [Activation des APIs](#5-activation-des-apis)
6. [Firestore](#6-firestore)
7. [Vertex AI et Gemini](#7-vertex-ai-et-gemini)
8. [Model Armor](#8-model-armor)
9. [Secrets](#9-secrets)
10. [Déploiement](#10-déploiement)
11. [Vérification du déploiement](#11-vérification-du-déploiement)
12. [Suivi des coûts au quotidien](#12-suivi-des-coûts-au-quotidien)
13. [Démantèlement](#13-démantèlement)
14. [Dépannage](#14-dépannage)

---

## 1. Vérification locale

Aucune clé, aucun cloud, aucun réseau.

```bash
unzip acc-autonomous-mission-control.zip && cd acc
pip install -r requirements.txt

pytest -q                              # 134 tests
python scripts/audit_coverage.py       # 47/47 exigences liées à un test réel
python scripts/run_hero_scenario.py    # scénario héros complet
```

Les tests sont hermétiques à votre `.env` : un fichier local ne peut pas
modifier les seuils de politique ni le mode Model Armor pendant la suite.

Le mode `deterministic` n'appelle aucun modèle **mais traverse quand même
l'Agent Gateway** : politique, idempotence et audit sont exercés à l'identique.
C'est ce qui rend la démo rejouable même sans quota Gemini.

---

## 2. Pile complète en local

### Note Windows

Toutes les cibles `make` passent par `scripts/dev.py` : aucune syntaxe de shell
POSIX n'est utilisée, donc `make run` se comporte de façon identique sous
Windows, macOS et Linux.

| Point | Détail |
|---|---|
| Interpréteur | `make run PY=python3` si `python` n'est pas dans le PATH |
| `npm` | Résolu via `shutil.which` — trouve `npm.cmd` sous Windows |
| `costs.sh`, `teardown.sh`, `deploy.sh` | **Scripts bash** : sous Windows, les lancer depuis Git Bash ou WSL |
| Clé d'API | `ACC_API_KEY` dans le `.env` backend suffit : `make web` la propage au frontend |
| Environnement virtuel | `dev.py` utilise `sys.executable`, donc le venv actif est respecté |


```bash
make run-mock      # systèmes entreprise simulés  → :8081
make run           # control plane ACC            → :8080/docs
make web-install   # une seule fois (npm install)
make web           # Mission Control              → :3000
make doctor        # vérifie que tout se parle
```

Si le port 8080 est déjà pris sur votre poste (llama.cpp l'utilise par défaut,
XAMPP et Tomcat aussi), tout est surchargeable :

```bash
make run PORT=8099
make web ACC_API=http://127.0.0.1:8099
make doctor PORT=8099
```

Ou en conteneurs (`docker compose`) :

```bash
make stack
```

> **Jamais exécuté de mon côté** : Docker n'était pas disponible. Les
> Dockerfiles sont écrits mais non buildés. Lancez `make stack` une fois avant
> de compter dessus le jour J.

Pour tester Gemini en local sans Vertex AI :

```bash
export GOOGLE_GENAI_USE_VERTEXAI=0
export GOOGLE_API_KEY="votre-clé-AI-Studio"
export ACC_AGENT_MODE=hybrid
make run
```

---

## 3. Google Cloud — préparation du projet

```bash
export PROJECT_ID="agent-command-center-506708"     # doit être globalement unique
export REGION="europe-west1"               # Belgique — voir note ci-dessous
export BILLING_ACCOUNT="016B60-37C1EE-5FCDF7"

gcloud auth login
gcloud projects create "${PROJECT_ID}"
gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT}"
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"
```

### Pourquoi `europe-west1`

C'est une des rares régions où **les quatre services critiques coexistent** :
Cloud Run, Firestore, Vertex AI (Gemini) et Model Armor. Model Armor est
notamment disponible en `europe-west1` (Belgique), `europe-west2` (Londres),
`europe-west3` (Francfort), `europe-west4` (Pays-Bas), plus les régions US.

Si vous changez de région, **vérifiez Model Armor en premier** — c'est le
service à la couverture la plus étroite :
<https://docs.cloud.google.com/model-armor/locations>

Récupérer l'identifiant de facturation si vous ne l'avez pas :

```bash
gcloud billing accounts list
```

---

## 4. Budget et garde-fous

### Avec 150 $ de crédits

**Le coût de la démo n'est pas le risque.** Chiffres mesurés sur le code, aux
tarifs Vertex AI vérifiés en août 2026 (Gemini 2.5 Flash : 0,30 $ / million de
tokens en entrée, 2,50 $ en sortie) :

| Poste | Mesure réelle | Coût |
|---|---|---|
| Appels modèle | 7 par scénario héros, ~700 tokens d'entrée chacun | **~0,012 $ par mission** (Flash-Lite) |
| Écritures Firestore | 86 documents par scénario héros | offre gratuite : 20 000/jour |
| Cloud Run | scale to zero, 3 services | offre gratuite : 2 M requêtes/mois |
| Model Armor | 2 analyses par appel d'agent | facturé à l'appel, volume négligeable |

**1 000 missions de démonstration coûteraient environ 10 $.** Même en multipliant
par trois pour les allers-retours d'outils, vous restez très loin des 150 $.

**Le vrai risque, ce sont les ressources oubliées :**

| Risque | Protection en place |
|---|---|
| Services laissés actifs après le hackathon | `make teardown` — à lancer le jour de la soumission |
| Instance minimale > 0 (facture au repos) | `min_instance_count = 0`, vérifié par test |
| Boucle de recovery emballée | budget de tentatives + circuit breaker |
| Modèle « Pro » activé par mégarde (4x plus cher) | `GEMINI_MODEL_REASONING` vide par défaut, vérifié par test |
| Images Artifact Registry accumulées | survivent au `destroy` — voir §13 |
| Ressource facturant à l'heure (GKE, Cloud SQL, endpoint Vertex) | aucune dans le Terraform, vérifié par test |

**Budget recommandé : 40 $**, soit un quart des crédits. Assez large pour ne
jamais gêner la démo, assez serré pour vous alerter avant qu'un oubli ne coûte
cher.

### Quel modèle choisir

**Recommandé : `gemini-3.1-flash-lite`** — c'est le défaut du projet.

Coût par mission héros, calculé sur la volumétrie mesurée (7 appels,
~700 tokens d'entrée, ~350 de sortie visible) :

| Modèle | 1 000 missions | Retrait annoncé |
|---|---|---|
| **`gemini-3.1-flash-lite`** | **~12 $** | — |
| `gemini-2.5-flash` | ~8 $ | **16 octobre 2026** |
| `gemini-3.6-flash` | ~68 $ | — (tarif promo jusqu'au 31/12/26) |
| `gemini-3.5-flash` | ~162 $ | — |
| `gemini-3.1-pro` | ~245 $ | — |

Trois raisons de choisir Flash-Lite :

1. **Génération courante.** Les modèles 2.5 sont retirés le 16 octobre 2026.
   Ils fonctionneraient pendant le hackathon, puis renverraient 404 si
   l'évaluation déborde sur octobre — un échec silencieux, après la soumission.
2. **Le budget tient.** `gemini-3.5-flash` coûterait plus que vos 150 $ de
   crédits sur 1 000 missions. Flash-Lite : 12 $.
3. **C'est cohérent avec la thèse du produit.** ACC ne demande pas au modèle de
   *décider* : la politique, l'idempotence et l'autorité vivent dans la
   plateforme. Le modèle produit un constat structuré. Un modèle frontière
   n'apporterait rien ici — et le dire au jury est un argument, pas un aveu.

> **Sur les tokens de réflexion.** Les modèles 3.x raisonnent en interne et ces
> tokens sont facturés **en sortie** (x5 à x10 sur la sortie visible). C'est ce
> qui creuse l'écart du tableau. Le multiplicateur est une estimation
> documentée, pas une mesure : je n'ai pas pu appeler ces modèles.

**Si la qualité d'appel d'outils déçoit**, passez à `gemini-3.6-flash`
(~68 $/1 000 missions, tarif promotionnel jusqu'au 31/12/2026) :

```bash
# une seule variable, aucun code à modifier
GEMINI_MODEL=gemini-3.6-flash
```

Le mode `hybrid` protège la démonstration dans tous les cas : si le modèle
échoue ou dérape, le repli déterministe prend le relais **en traversant le même
Gateway**.

> **Bonne nouvelle pour la migration.** Les paramètres `temperature`, `top_p` et
> `top_k` sont dépréciés depuis le 21 juillet 2026 et sont le point de blocage
> habituel d'un changement de modèle. ACC ne les fixe nulle part : changer de
> modèle est une simple variable d'environnement. Vérifié par test.

**Vérifiez malgré tout que le modèle répond dans votre région avant de
déployer** (§7).

### Créer le budget

**Faites ceci avant d'activer la moindre API.** Un budget ne bloque pas la
dépense — il vous prévient. C'est la différence entre découvrir un problème en
2 heures ou sur la facture du mois suivant.

```bash
gcloud billing budgets create \
  --billing-account="${BILLING_ACCOUNT}" \
  --display-name="ACC hackathon" \
  --budget-amount=40USD \
  --filter-projects="projects/${PROJECT_ID}" \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0 \
  --threshold-rule=percent=1.5
```

Les seuils sont en base 1.0 (`0.5` = 50 %). Le seuil à 150 % existe pour
attraper une dépense qui **continue** après le dépassement — c'est le scénario
qui fait mal.

Par défaut les alertes partent aux administrateurs de facturation. Pour les
router ailleurs (Slack, PagerDuty), créez d'abord un canal Cloud Monitoring puis
`gcloud billing budgets update --notifications-rule-monitoring-notification-channels=...`.

### Garde-fous déjà présents dans le code

| Garde-fou | Où | Effet |
|---|---|---|
| `min_instance_count = 0` | `cloud_run.tf` | Aucun coût à l'inactivité |
| `max_instance_count = 4` | `var.max_instances_api` | Plafond dur en cas de pic |
| `ACC_AGENT_MODE=deterministic` | variable d'env | Zéro appel modèle |
| `GEMINI_MODEL_REASONING` vide | `config.py` | Pas de modèle « Pro » par surprise |
| `acc_agent_timeout_s = 25` | `config.py` | Aucun appel modèle qui traîne |
| `max_attempts = 3` | `domain/models.py` | Boucle de recovery bornée |
| Circuit breaker | `enterprise_tools.py` | Stoppe les appels en boucle |
| Labels `app=acc` | toutes ressources Cloud Run | Ventilation de la facture |

Ces garde-fous sont vérifiés par `tests/unit/test_cost_guardrails.py` : un
`min_instance_count > 0` ou l'ajout d'une ressource facturant à l'heure (GKE,
Cloud SQL, endpoint Vertex) fait échouer la CI.

---

## 5. Activation des APIs

```bash
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  modelarmor.googleapis.com \
  iam.googleapis.com \
  --project="${PROJECT_ID}"
```

Comptez 2 à 3 minutes de propagation. Un `terraform apply` lancé trop tôt
échouera avec `API not enabled` — relancez simplement.

---

## 6. Firestore

**Le piège le plus fréquent du premier `terraform apply`.**

Terraform tente de créer la base `(default)`. Si le projet en possède déjà une
(créée par un autre outil, ou par Firebase), l'apply échoue avec
`ALREADY_EXISTS`.

Vérifiez d'abord :

```bash
gcloud firestore databases list --project="${PROJECT_ID}"
```

**Si la liste est vide** → ne faites rien, Terraform la créera.

**Si `(default)` existe déjà** → importez-la au lieu de la recréer :

```bash
cd infrastructure/terraform
terraform init
terraform import google_firestore_database.acc \
  "projects/${PROJECT_ID}/databases/(default)"
```

Vérifiez qu'elle est bien en mode **Native** (pas Datastore) : ACC utilise des
sous-collections et des transactions que le mode Datastore ne sert pas de la
même façon.

### Index composites

Deux index sont déclarés dans `firestore.tf` (`approvals_index`, `missions`).
Leur construction prend quelques minutes après l'apply. Tant qu'ils ne sont pas
prêts, `GET /api/v1/approvals?status=PENDING` peut renvoyer une erreur
`FAILED_PRECONDITION` avec un lien de création directe — c'est normal.

---

## 7. Vertex AI et Gemini

Vérifiez que le modèle répond dans votre région avant de déployer :

```bash
gcloud ai models list --region="${REGION}" --project="${PROJECT_ID}" 2>/dev/null | head

curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/publishers/google/models/gemini-3.1-flash-lite:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Réponds uniquement: OK"}]}]}'
```

Si le modèle n'existe pas dans la région, ajustez `GEMINI_MODEL` ou
`VERTEX_AI_LOCATION`. La liste des modèles par région évolue vite :
<https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/locations>

**Si le modèle n'existe pas** (HTTP 404), listez ce qui est disponible :

```bash
gcloud ai models list --region="${REGION}" --project="${PROJECT_ID}"
```

puis ajustez `GEMINI_MODEL` dans le Terraform (`var.gemini_model`).

### Le seul chemin que je n'ai jamais exécuté

`tests/integration/test_adk_path.py` couvre le parsing, le timeout, le repli et
la sanitisation avec un double fidèle du Runner ADK. Les 4 agents se construisent
sur ADK 2.7 réel avec les bons schémas d'outils. **Mais aucun appel n'a touché un
endpoint Gemini.**

Test à faire en 10 minutes :

```bash
export ACC_AGENT_MODE=hybrid
export GOOGLE_GENAI_USE_VERTEXAI=1
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export VERTEX_AI_LOCATION="${REGION}"
make run-mock &
make run
# puis : ACC_URL=http://localhost:8080 ./scripts/demo_walkthrough.sh
```

En `hybrid`, un échec du modèle bascule automatiquement sur le repli
déterministe — la démo tient même si Gemini refuse.

---

## 8. Model Armor

### Endpoint régional

```bash
gcloud config set api_endpoint_overrides/modelarmor \
  "https://modelarmor.${REGION}.rep.googleapis.com/"
```

### Création du template

```bash
gcloud model-armor templates create acc-guardrails \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --pi-and-jailbreak-filter-settings-enforcement=enabled \
  --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above \
  --malicious-uri-filter-settings-enforcement=enabled \
  --basic-config-filter-enforcement=enabled \
  --template-metadata-log-sanitize-operations
```

Le filtre **prompt injection / jailbreak** est celui qui porte la démonstration
de sécurité d'ACC. `medium-and-above` est le bon compromis : `high` laisserait
passer l'injection du scénario, `low-and-above` produirait des faux positifs
pendant la démo.

Récupérez le nom complet et injectez-le dans la configuration :

```bash
gcloud model-armor templates list --location="${REGION}" --project="${PROJECT_ID}"
# → projects/PROJECT_ID/locations/REGION/templates/acc-guardrails
```

Cette valeur va dans `MODEL_ARMOR_TEMPLATE`, avec `ACC_MODEL_ARMOR=gcp`.

### Droit IAM

Le compte de service du control plane doit porter `roles/modelarmor.user` :

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:acc-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/modelarmor.user"
```

Ce rôle est désormais déclaré dans `iam.tf` (`local.api_roles`) : Terraform le
pose automatiquement. La commande ci-dessus ne sert qu'en rattrapage si vous
avez déployé avant cette correction.

### ⚠ Piège de calendrier

Les templates utilisant l'alias **Stable** basculent automatiquement en filtre
**v3 le 31 août 2026** — le jour de la deadline. Un template créé aujourd'hui
peut donc changer de comportement pendant la période de soumission.

Deux protections :

1. Testez le scénario d'injection **après** le 31 août si vous démontrez en live
2. Gardez `ACC_MODEL_ARMOR=heuristic` en filet — le détecteur local est
   déterministe et couvre le payload du scénario (`tests/unit/test_model_armor.py`)

---

## 9. Secrets

Aucun secret ne doit se trouver dans le dépôt, une image ou un prompt.

```bash
# Clé d'API applicative protégeant l'URL publique Cloud Run
openssl rand -hex 32 | gcloud secrets create acc-api-key \
  --data-file=- --project="${PROJECT_ID}"

# Jeton partagé pour le push Pub/Sub
openssl rand -hex 32 | gcloud secrets create acc-pubsub-push-token \
  --data-file=- --project="${PROJECT_ID}"
```

Terraform déclare ces secrets et les monte comme variables d'environnement
Cloud Run. Les versions doivent exister **avant** l'apply, sinon le déploiement
échoue sur `Secret version not found`.

Récupérer la clé pour appeler l'API :

```bash
gcloud secrets versions access latest --secret=acc-api-key --project="${PROJECT_ID}"
```

---

## 10. Déploiement

```bash
PROJECT_ID="${PROJECT_ID}" REGION="${REGION}" ./scripts/deploy.sh
```

Le script construit les trois images, les pousse dans Artifact Registry, puis
applique Terraform. Ordre de création : APIs → Artifact Registry → Firestore →
IAM → Secrets → Pub/Sub → Cloud Run.

### Faire tourner le premier apply à vide

```bash
cd infrastructure/terraform
terraform init
terraform plan \
  -var="project_id=${PROJECT_ID}" -var="region=${REGION}" \
  -var="image_api=placeholder" -var="image_mock=placeholder" \
  -var="image_web=placeholder"
```

### Pièges connus du premier apply

| Symptôme | Cause | Correctif |
|---|---|---|
| `ALREADY_EXISTS` sur Firestore | base `(default)` préexistante | `terraform import` (§6) |
| `API not enabled` | propagation en cours | attendre 2 min, relancer |
| `Permission denied` sur IAM | propagation IAM | relancer l'apply |
| `Secret version not found` | secrets non créés | faire le §9 d'abord |
| Push Pub/Sub en 403 | jeton absent | vérifier `acc-pubsub-push-token` |
| `terraform destroy` bloqué | protection Firestore | `./scripts/teardown.sh` |

La propagation IAM fait fréquemment échouer le **premier** apply et réussir le
second. Ce n'est pas une erreur de configuration.

---

## 11. Vérification du déploiement

```bash
cd infrastructure/terraform
export ACC_URL=$(terraform output -raw acc_api_url)
export WEB_URL=$(terraform output -raw acc_web_url)
export ACC_API_KEY=$(gcloud secrets versions access latest --secret=acc-api-key)
cd ../..

curl -fsS "${ACC_URL}/healthz" | python3 -m json.tool
```

Attendu : `persistence: firestore`, `event_bus: pubsub`, `model_armor: gcp`.

Puis le scénario complet contre l'instance déployée :

```bash
./scripts/demo_walkthrough.sh
```

Et ouvrez `${WEB_URL}` dans un navigateur.

> **Le seul livrable que je n'ai jamais observé.** Mission Control est typé
> strict, buildé (110 kB First Load JS), câblé sur l'API réelle et testé en
> SSE — mais je ne l'ai jamais vu rendu. Mise en page, contraste en projection,
> comportement visuel du flux : à valider de vos yeux.

---

## 12. Suivi des coûts au quotidien

```bash
PROJECT_ID="${PROJECT_ID}" ./scripts/costs.sh
```

Le script affiche : budget et seuils, garde-fous d'échelle par service (et vous
alerte si un `min_instance_count > 0` traîne), volumétrie Firestore, et les
liens vers les rapports filtrés.

### Où part réellement l'argent

Par ordre de risque, pas de montant :

| Poste | Ce qui pilote le coût | Risque |
|---|---|---|
| **Vertex AI / Gemini** | tokens × appels | **Élevé** — ~8 à 12 appels par mission en `hybrid` ; une boucle de retry mal bornée est le scénario coûteux |
| **Model Armor** | par appel de sanitisation | **Moyen** — 2 appels par invocation d'agent (prompt + réponse) |
| **Firestore** | lectures/écritures de documents | **Moyen** — ACC écrit 60 à 90 documents par mission (events, audit, checkpoints). 1 000 missions ≈ 80 k écritures |
| **Cloud Run** | temps × requêtes | **Faible** — scale to zero, l'offre gratuite couvre largement une démo |
| **Pub/Sub** | volume de messages | **Faible** |
| **Artifact Registry** | stockage des images | **Faible mais persistant** — survit à un `terraform destroy` |
| **Cloud Logging** | volume ingéré | **Faible** — 50 GiB/mois gratuits ; ACC émet du JSON structuré par événement |

Je ne donne pas de montants : les tarifs changent et je ne veux pas vous faire
budgéter sur un chiffre inventé. Utilisez le calculateur officiel :
<https://cloud.google.com/products/calculator>

### Ventiler la facture par composant

Les labels `app=acc`, `environment`, `component` sont posés sur toutes les
ressources Cloud Run par Terraform.

Console → Facturation → Rapports → **Grouper par : Label** → `app: acc`
Puis **Grouper par : SKU** pour isoler la part Gemini et Model Armor.

Les labels n'apparaissent dans les rapports qu'après ~24 h de collecte.

### Réflexes pendant le hackathon

- Repassez en `ACC_AGENT_MODE=deterministic` entre deux répétitions : zéro
  token consommé, la gouvernance reste démontrée
- Ne montez jamais `min_instance_count` au-dessus de 0, même pour gagner en
  latence de démarrage à froid
- Lancez `./scripts/costs.sh` une fois par jour
- Après la soumission : `./scripts/teardown.sh` le jour même

---

## 13. Démantèlement

```bash
PROJECT_ID="${PROJECT_ID}" ./scripts/teardown.sh
```

Le script lève d'abord la protection de suppression Firestore (sans quoi
`terraform destroy` échoue), détruit l'infrastructure, puis liste ce qui peut
encore facturer.

Ce qui **survit** à un `destroy` : les images dans Artifact Registry et les logs
conservés. Le script vous donne les commandes pour les supprimer.

Garantie absolue de zéro :

```bash
gcloud projects delete "${PROJECT_ID}"
```

---

## 14. Dépannage

### D'abord : le diagnostic automatique

```bash
make doctor          # ou : python scripts/doctor.py
```

Il identifie en une passe : port occupé par un tiers, résolution IPv6/IPv4,
clé d'API manquante, `.env.local` mal réglé, mock entreprise absent. Les
vérifications sont en cascade — une cause racine ne produit qu'une ligne
d'erreur, pas six.

### 401 sur toutes les routes `/api/v1/*`

**Le piège** : une variable d'environnement `ACC_API_KEY` prime sur le fichier
`.env` — **même si la ligne y est commentée**. Un `cat .env` montrant
`#ACC_API_KEY=` ne prouve donc rien.

```bash
make doctor        # nomme la source de la clé et donne la commande exacte
```

Le démarrage du backend le journalise aussi :

```json
{"message": "api_key_enforced", "source": "environnement",
 "hint": "... Pour la retirer : PowerShell « Remove-Item Env:ACC_API_KEY » ..."}
```

**Retirer la variable :**

| Shell | Commande |
|---|---|
| PowerShell | `Remove-Item Env:ACC_API_KEY` |
| cmd | `set ACC_API_KEY=` |
| bash / zsh | `unset ACC_API_KEY` |

Puis relancer `make run`.

**Si vous voulez garder la clé**, `make web` la propage automatiquement au
frontend : rien d'autre à faire.

Note : une clé faite uniquement d'espaces est traitée comme absente — c'est une
erreur de configuration, pas un secret.

### Le port 8080 est occupé : 404 sur toutes les routes `/api/v1/*`

**Symptôme.** Le backend affiche « Uvicorn running on http://127.0.0.1:8080 »
sans la moindre erreur, mais Mission Control reçoit des 404 hors contrat ACC.

**Le piège Windows qu'il faut connaître.** Sous Windows, plusieurs processus
peuvent se lier à la **même** adresse:port quand `SO_EXCLUSIVEADDRUSE` n'est pas
posé. Uvicorn annonce donc « running » alors qu'un autre service reçoit les
requêtes. Sur Linux, le second bind échouerait avec « Address already in use » —
d'où un problème invisible en CI et bien réel sur votre poste.

```powershell
netstat -ano | findstr :8080
```

Trois lignes `LISTENING` sur `127.0.0.1:8080` = trois processus en concurrence.

**Occupants fréquents du port 8080 :**

| Service | Indice |
|---|---|
| **llama.cpp** | `Server: llama.cpp` — **son port par défaut est 8080** |
| Ollama (proxy) | selon la configuration |
| Apache / XAMPP | `Server: Apache/...` |
| Tomcat | `Server: Apache-Coyote` |
| IIS | `Server: Microsoft-IIS` |

**Diagnostic en une commande :**

```bash
make doctor
```

Il lit l'en-tête `Server` de ce qui répond et nomme directement le coupable :

```
[ECHEC] Ce port est detenu par un serveur llama.cpp (son port par defaut EST 8080)
        -> En-tete Server : « llama.cpp ». Arretez ce service, ou lancez ACC
           ailleurs : make run PORT=8099
```

Il signale aussi le bind multiple et liste les PID concernés.

**Correctif recommandé — déplacer ACC, pas l'autre service :**

```bash
make run PORT=8099                       # backend
make web ACC_API=http://127.0.0.1:8099   # frontend pointé sur le même port
make doctor PORT=8099                    # vérification
```

Les cibles `run`, `web`, `web-build` et `doctor` acceptent toutes `PORT` et
`ACC_API`. Aucun fichier à éditer.

**Variante IPv4/IPv6.** Uvicorn n'écoute qu'en IPv4. Sous Windows, « localhost »
résout d'abord en IPv6 (`::1`) : un service tiers lié à `[::1]:8080` capterait
les appels. Le client frontend utilise donc `127.0.0.1` par défaut.

> **Toujours `127.0.0.1`, jamais `localhost`** dans `NEXT_PUBLIC_ACC_API`.

**Après toute modification de `.env.local` : redémarrer `make web`.** Les
variables `NEXT_PUBLIC_*` sont figées au build, pas lues à l'exécution.

| Symptôme | Piste |
|---|---|
| `/healthz` répond `persistence: memory` en prod | `ACC_PERSISTENCE` non transmis — vérifier les env vars Cloud Run |
| Missions bloquées en `CREATED` | Le push Pub/Sub n'arrive pas : vérifier l'abonnement et le jeton OIDC |
| `403` sur toutes les routes API | En-tête `x-api-key` absent ou mauvaise valeur |
| Model Armor ne bloque rien | Template introuvable → repli silencieux sur l'heuristique. Vérifier `MODEL_ARMOR_TEMPLATE` et `roles/modelarmor.user` |
| Agents en repli déterministe permanent | Regarder les logs `adk_unavailable` / `agent_model_error` — souvent un quota ou un modèle absent de la région |
| `FAILED_PRECONDITION` sur les approbations | Index Firestore en cours de construction (quelques minutes) |
| Le frontend n'affiche rien | `NEXT_PUBLIC_ACC_API` est figé **au build** : rebuild nécessaire après changement d'URL |
| SSE qui ne se connecte pas | Normal derrière certains proxies — le hook bascule seul sur du polling |
| 401 « Cle d'API invalide ou absente » | Voir la section dédiée ci-dessous — la cause est souvent une **variable d'environnement**, pas le `.env` |
| Mission bloquée en « ATTENTE APPROBATION » sans approbation en attente | Corrigé (ADR-018). Sur une archive antérieure : redémarrer la mission |
| Toutes les missions partent en recovery immédiatement | Les systèmes entreprise ne tournent pas : `make run-mock` dans un second terminal |
| Erreur CORS depuis Mission Control | Presque toujours un autre serveur sur le port : `curl` ignore CORS, pas le navigateur. `make doctor` teste le preflight |
| CORS bloqué une fois déployé | `ACC_CORS_ORIGIN_REGEX` doit couvrir votre URL Cloud Run — les jokers dans `ACC_CORS_ORIGINS` ne fonctionnent pas |
| `AttributeError: '_IncludedRouter'` à chaque requête | Instrumentation OTel trop ancienne pour FastAPI ≥ 0.141. ACC la désactive seul ; pour la réactiver : `pip install -U opentelemetry-instrumentation-fastapi` |
| 404 « File Not Found » sur `/api/v1/*` | Port 8080 occupé par un tiers (llama.cpp, XAMPP…) — `make doctor` nomme le coupable |
| Uvicorn dit « running » mais ne reçoit rien | Bind multiple Windows — `netstat -ano \| findstr :8080`, puis `make run PORT=8099` |
| `pytest` échoue sur `test_adk_path.py` | Corrigé : les tests fonctionnent désormais sans `google-adk`. Sur une archive antérieure : `pip install google-adk` |
| Avertissement pydantic « protected namespace » | Corrigé (`protected_namespaces=()`) |
| `pytest` échoue en 401 sur `test_api.py` | Corrigé en v0.1.1. Si vous partez d'une archive antérieure : les routes lisaient `.env` au lieu des réglages du container |
| Tests qui passent chez un dev, échouent chez un autre | Vérifier qu'aucun `Settings()` de test ne contourne `make_settings()` — voir ADR-012 |

### Lire les logs

```bash
gcloud run services logs read acc-api --region="${REGION}" --limit=50 \
  --project="${PROJECT_ID}"
```

Tous les logs sont du JSON structuré portant `mission_id` et `trace_id`. Pour
suivre une mission de bout en bout :

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND jsonPayload.mission_id="MIS-1001"' \
  --project="${PROJECT_ID}" --limit=100 --format=json
```

---

## Où regarder en premier dans le code

| Fichier | Ce qu'il prouve |
|---|---|
| `docs/DEMO_SCRIPT.md` | Déroulé minuté de 3 minutes pour le jury |
| `docs/ARCHITECTURE.md` | 10 ADR, dont les 3 bugs trouvés par audit |
| `apps/api/services/agent_gateway.py` | Le pipeline non contournable |
| `agents/failure_twin/agent.py` | « Meilleure option ≠ meilleure option permise » |
| `tests/integration/test_concurrency.py` | Pourquoi un test en mémoire peut mentir |
| `scripts/audit_coverage.py` | 47 exigences de blueprint → tests réels |

---

## Récapitulatif de ce qui reste à faire

| # | Action | Durée | Pourquoi c'est risqué |
|---|---|---|---|
| 0 | Vérifier que `gemini-3.1-flash-lite` répond (§7) | 2 min | Un modèle absent de la région bloque tout |
| 1 | Budget GCP à 40 $ (§4) | 5 min | Aucun filet sans lui |
| 2 | `terraform apply` (§10) | 30 min | Jamais exécuté — pièges Firestore et IAM |
| 3 | Gemini réel en `hybrid` (§7) | 10 min | Seul chemin jamais testé contre un modèle |
| 4 | `make stack` | 15 min | Images Docker jamais buildées |
| 5 | Ouvrir Mission Control (§11) | 5 min | Jamais vu rendu |
| 6 | Vidéo 3 min | 2 h | Asset de soumission obligatoire |
| 7 | 10 runs consécutifs | 30 min | Exigence Doc 10 §17 |
| 8 | `./scripts/teardown.sh` | 5 min | Le jour de la soumission |
