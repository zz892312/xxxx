import subprocess
import logging
import os
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import requests
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ── CONFIG ────────────────────────────────────────────────────────────────────

# Repos allowed to call the broker
ALLOWED_REPOS = os.getenv("ALLOWED_REPOS", "myorg/github-abc,myorg/github-xyz").split(",")

# The exact reusable workflow that must be referenced
REQUIRED_WORKFLOW = os.getenv("REQUIRED_WORKFLOW", "myorg/github-drt/.github/workflows/deploy.yml")

# Only allow deployments from this branch
ALLOWED_BRANCH = os.getenv("ALLOWED_BRANCH", "main")

# Cluster API server
OC_SERVER = os.getenv("OC_SERVER", "https://your-cluster:6443")

# Token duration
TOKEN_DURATION = os.getenv("TOKEN_DURATION", "5m")

# Namespace → allowed repo mapping (optional strict enforcement)
# e.g. "team-abc:myorg/github-abc,team-xyz:myorg/github-xyz"
NAMESPACE_REPO_MAP = {}
raw_map = os.getenv("NAMESPACE_REPO_MAP", "")
if raw_map:
    for entry in raw_map.split(","):
        ns, repo = entry.split(":")
        NAMESPACE_REPO_MAP[ns.strip()] = repo.strip()


# ── REQUEST MODEL ─────────────────────────────────────────────────────────────

class DeployRequest(BaseModel):
    namespace: str
    run_id: str
    repo: str          # e.g. "myorg/github-abc"


# ── VALIDATION ────────────────────────────────────────────────────────────────

def validate_github_token(token: str, repo: str, run_id: str) -> dict:
    """
    Ask GitHub API to confirm the token is real
    and belongs to the claimed repo/run.
    The caller cannot fake this — GitHub is the authority.
    """
    response = requests.get(
        f"https://api.github.com/repos/{repo}/actions/runs/{run_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        timeout=10
    )

    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or expired GITHUB_TOKEN")

    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="Token does not have access to this repo/run")

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Run not found — token may belong to a different repo")

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {response.status_code}")

    return response.json()


def check_run(run: dict, repo: str, namespace: str):
    """
    Enforce all security checks against the GitHub run object.
    """

    # 1. Repo must be in allowlist
    actual_repo = run.get("repository", {}).get("full_name", "")
    if actual_repo not in ALLOWED_REPOS:
        logger.warning(f"Rejected: repo {actual_repo} not in allowlist")
        raise HTTPException(status_code=403, detail=f"Repo {actual_repo} is not allowed")

    # 2. Must have come from our reusable workflow
    referenced = run.get("referenced_workflows", [])
    workflow_paths = [w.get("path", "") for w in referenced]
    if not any(REQUIRED_WORKFLOW in path for path in workflow_paths):
        logger.warning(f"Rejected: referenced_workflows={workflow_paths}")
        raise HTTPException(status_code=403, detail="Request did not originate from the required workflow")

    # 3. Must be deploying from the allowed branch
    branch = run.get("head_branch", "")
    if branch != ALLOWED_BRANCH:
        logger.warning(f"Rejected: branch={branch}")
        raise HTTPException(status_code=403, detail=f"Deployments only allowed from branch: {ALLOWED_BRANCH}")

    # 4. Run must be in progress (not queued or already done)
    status = run.get("status", "")
    if status not in ("in_progress", "queued"):
        logger.warning(f"Rejected: run status={status}")
        raise HTTPException(status_code=403, detail=f"Run is not active (status: {status})")

    # 5. Namespace → repo enforcement (if configured)
    if NAMESPACE_REPO_MAP:
        allowed_repo_for_ns = NAMESPACE_REPO_MAP.get(namespace)
        if allowed_repo_for_ns and allowed_repo_for_ns != actual_repo:
            logger.warning(f"Rejected: {actual_repo} tried to deploy to namespace {namespace}")
            raise HTTPException(status_code=403, detail=f"Repo {actual_repo} is not allowed to deploy to namespace {namespace}")


# ── TOKEN ISSUANCE ────────────────────────────────────────────────────────────

def issue_temp_oc_token(namespace: str) -> str:
    """
    Issue a short-lived OpenShift token for the deploy-sa ServiceAccount.
    Token is a bound JWT with hard expiry — auto-rejected by cluster after duration.
    """
    result = subprocess.run(
        [
            "oc", "create", "token", "deploy-sa",
            "--namespace", namespace,
            "--duration", TOKEN_DURATION
        ],
        capture_output=True,
        text=True,
        timeout=15
    )

    if result.returncode != 0:
        logger.error(f"oc create token failed: {result.stderr}")
        raise HTTPException(status_code=500, detail="Failed to issue OC token")

    return result.stdout.strip()


# ── ENDPOINT ──────────────────────────────────────────────────────────────────

@app.post("/auth")
def auth(
    payload: DeployRequest,
    authorization: str = Header(...)
):
    token = authorization.removeprefix("Bearer ").strip()

    logger.info(f"Deploy request: repo={payload.repo} run={payload.run_id} namespace={payload.namespace}")

    # Step 1 — validate token is real and belongs to the claimed repo/run
    run = validate_github_token(token, payload.repo, payload.run_id)

    # Step 2 — enforce all security checks
    check_run(run, payload.repo, payload.namespace)

    # Step 3 — issue short-lived OC token
    temp_token = issue_temp_oc_token(payload.namespace)

    logger.info(f"Issued temp token: repo={payload.repo} namespace={payload.namespace} duration={TOKEN_DURATION}")

    return {"token": temp_token, "duration": TOKEN_DURATION}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
