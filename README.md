# IoT Microservices Sample (ARM64) + GitHub Actions to Google Artifact Registry

This repository contains three sample Python services for an IoT pipeline and a CI/CD workflow that builds ARM64 Docker images and pushes them to **Google Artifact Registry (GAR)**.

## Services

1. **Data Ingestor** (`iot/ingestor:v1`)
   - Reads sensor events from MQTT (`INGEST_MODE=mqtt`) or UNIX local socket (`INGEST_MODE=socket`).
   - Writes raw events into Redis stream `sensor:raw`.

2. **Processor** (`iot/processor:v1`)
   - Reads raw stream data from Redis.
   - Applies filtering (`FILTER_MIN`, `FILTER_MAX`) and rolling average aggregation (`WINDOW_SIZE`).
   - Writes processed payload to `sensor:processed`.

3. **Sync Agent** (`iot/sync-agent:v1`)
   - Reads processed events.
   - Checks endpoint/network availability.
   - Uploads to cloud API and retries when unavailable.

---

## Project Structure

```text
.
├── ingestor/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── processor/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── sync-agent/
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
└── .github/workflows/
    └── build-and-push-gar.yml
```

---

## Build Locally (optional)

```bash
docker build -t iot/ingestor:v1 ./ingestor
docker build -t iot/processor:v1 ./processor
docker build -t iot/sync-agent:v1 ./sync-agent
```

---

## GitHub Actions Pipeline

Workflow file: `.github/workflows/build-and-push-gar.yml`

### Trigger
- Push to `main` or `master`
- Push tags like `v1.0.0`
- Manual run (`workflow_dispatch`)

### What it does
- Authenticates GitHub Actions to Google Cloud using **Workload Identity Federation**.
- Builds each service with Docker Buildx for platform `linux/arm64`.
- Pushes images to Artifact Registry.

---

## Connect GitHub to GCP and push images to Artifact Registry

Recommended approach: **Workload Identity Federation** (no long-lived JSON key).

### 1) Create Artifact Registry repository

```bash
gcloud artifacts repositories create iot-images \
  --repository-format=docker \
  --location=us-central1 \
  --description="IoT container images"
```

### 2) Create service account for CI

```bash
gcloud iam service-accounts create github-gar-pusher \
  --display-name="GitHub GAR Pusher"
```

Grant push permissions:

```bash
gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:github-gar-pusher@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

### 3) Create Workload Identity Pool + Provider

```bash
gcloud iam workload-identity-pools create github-pool \
  --location="global" \
  --display-name="GitHub Pool"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository"
```

### 4) Allow your GitHub repo to impersonate the service account

```bash
gcloud iam service-accounts add-iam-policy-binding \
  github-gar-pusher@<PROJECT_ID>.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/attribute.repository/<GITHUB_ORG>/<GITHUB_REPO>"
```

### 5) Add GitHub repository secrets

Go to: **GitHub repo → Settings → Secrets and variables → Actions**

Add secrets:
- `GCP_WORKLOAD_IDENTITY_PROVIDER`:
  `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SERVICE_ACCOUNT`:
  `github-gar-pusher@<PROJECT_ID>.iam.gserviceaccount.com`

Add repository variables:
- `GCP_PROJECT_ID`: your project ID
- `GCP_REGION`: e.g. `us-central1`
- `GAR_REPOSITORY`: e.g. `iot-images`

### 6) Push to trigger workflow

```bash
git add .
git commit -m "Add IoT services and GAR CI pipeline"
git push origin main
```

### 7) Verify images in Artifact Registry

```bash
gcloud artifacts docker images list \
  us-central1-docker.pkg.dev/<PROJECT_ID>/iot-images/iot
```

---

## Example image names in GAR

After pipeline runs, images are pushed as:

- `<REGION>-docker.pkg.dev/<PROJECT_ID>/<GAR_REPOSITORY>/iot/ingestor:v1`
- `<REGION>-docker.pkg.dev/<PROJECT_ID>/<GAR_REPOSITORY>/iot/processor:v1`
- `<REGION>-docker.pkg.dev/<PROJECT_ID>/<GAR_REPOSITORY>/iot/sync-agent:v1`

and commit-specific tags:

- `.../ingestor:<GITHUB_SHA>`
- `.../processor:<GITHUB_SHA>`
- `.../sync-agent:<GITHUB_SHA>`

---

## Runtime env vars (quick reference)

### Ingestor
- `INGEST_MODE` (`mqtt` or `socket`)
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC`
- `SOCKET_PATH`
- `REDIS_HOST`, `REDIS_PORT`, `RAW_STREAM`

### Processor
- `REDIS_HOST`, `REDIS_PORT`
- `RAW_STREAM`, `PROCESSED_STREAM`
- `FILTER_MIN`, `FILTER_MAX`, `WINDOW_SIZE`

### Sync Agent
- `REDIS_HOST`, `REDIS_PORT`
- `PROCESSED_STREAM`
- `SYNC_ENDPOINT`, `SYNC_API_TOKEN`, `RETRY_SECONDS`

