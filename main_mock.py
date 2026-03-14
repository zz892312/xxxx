# main_mock.py
# Local development version of the broker.
# Replaces:
#   - GitHub API call  → mock response
#   - oc create token  → returns a fake token
#
# Run with: python main_mock.py
# Then test with: ./test_local.sh

import logging
import os
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

ALLOWED_REPOS     = ["myorg/github-abc", "myorg/github-xyz"]
REQUIRED_WORKFLOW = "myorg/github-drt/.github/workflows/deploy.yml"
ALLOWED_BRANCH    = "main"
TOKEN_DURATION    = "5m"

class DeployRequest(BaseModel):
    namespace: str
    run_id: str
    repo: str


def mock_github_api(token: str, repo: str, run_id: str) -> dict:
    """
    Simulates GitHub API response for local testing.
    In production (main.py) this is a real HTTP call to GitHub.
    """
    # Simulate token prefix check
    if not token.startswith("ghs_"):
        raise HTTPException(status_code=401, detail="Only GitHub Actions tokens (ghs_) accepted")

    # Return a mock run object that matches what GitHub would return
    return {
        "repository": {
            "full_name": repo
        },
        "referenced_workflows": [
            {
                "path": f"{REQUIRED_WORKFLOW}@refs/heads/main"
            }
        ],
        "head_branch": "main",
        "status": "in_progress"
    }


def mock_issue_oc_token(namespace: str) -> str:
    """
    Simulates oc create token for local testing.
    In production (main.py) this calls the real oc CLI.
    """
    fake_token = f"sha256~MOCK_TOKEN_FOR_{namespace}_expires_5m"
    logger.info(f"[MOCK] Issued fake OC token for namespace: {namespace}")
    return fake_token


def check_run(run: dict, repo: str, namespace: str):
    actual_repo = run.get("repository", {}).get("full_name", "")
    if actual_repo not in ALLOWED_REPOS:
        raise HTTPException(status_code=403, detail=f"Repo {actual_repo} not in allowlist")

    referenced = run.get("referenced_workflows", [])
    workflow_paths = [w.get("path", "") for w in referenced]
    if not any(REQUIRED_WORKFLOW in path for path in workflow_paths):
        raise HTTPException(status_code=403, detail="Workflow not from github-drt")

    branch = run.get("head_branch", "")
    if branch != ALLOWED_BRANCH:
        raise HTTPException(status_code=403, detail=f"Branch '{branch}' not allowed")

    status = run.get("status", "")
    if status not in ("in_progress", "queued"):
        raise HTTPException(status_code=403, detail=f"Run not active (status: {status})")


@app.post("/auth")
def auth(payload: DeployRequest, authorization: str = Header(...)):
    token = authorization.removeprefix("Bearer ").strip()

    logger.info(f"[MOCK] Deploy request: repo={payload.repo} run={payload.run_id} namespace={payload.namespace}")

    run = mock_github_api(token, payload.repo, payload.run_id)
    check_run(run, payload.repo, payload.namespace)
    temp_token = mock_issue_oc_token(payload.namespace)

    return {"token": temp_token, "duration": TOKEN_DURATION}


@app.get("/health")
def health():
    return {"status": "ok", "mode": "mock"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, reload=True)
