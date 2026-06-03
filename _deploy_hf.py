"""One-off HF Spaces deploy script. Reads HF_TOKEN + secrets from .env."""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(".env")
from huggingface_hub import HfApi

TOKEN = os.getenv("HF_TOKEN")
USERNAME = "AjaasMk"
REPO_ID = f"{USERNAME}/convrt"

if not TOKEN:
    print("ERROR: HF_TOKEN not found in .env")
    sys.exit(1)

api = HfApi(token=TOKEN)

# Verify token + identity
who = api.whoami()
print("Authenticated as:", who.get("name"))

# 1) Create the Space (private, Gradio SDK)
api.create_repo(
    repo_id=REPO_ID,
    repo_type="space",
    space_sdk="docker",
    private=False,
    exist_ok=True,
)
print(f"Space ready: {REPO_ID}")

# 2) Set Secrets (so the app runs without .env)
secrets = {
    "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "groq"),
    "GROQ_API_KEY": os.getenv("GROQ_API_KEY"),
    "GROQ_MODEL": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "APP_USERNAME": os.getenv("APP_USERNAME", "spicenutrition"),
    "APP_PASSWORD": os.getenv("APP_PASSWORD", "changeme123"),
}
for k, v in secrets.items():
    if v:
        api.add_space_secret(repo_id=REPO_ID, key=k, value=v)
        print(f"  secret set: {k}")

# 3) Upload project files (excluding secrets / regenerated data)
api.upload_folder(
    folder_path=".",
    repo_id=REPO_ID,
    repo_type="space",
    commit_message="Deploy Convrt SpiceNutrition agent",
    ignore_patterns=[
        ".env",
        "*.db", "*.db-shm", "*.db-wal",
        "chroma_db/**",
        "**/__pycache__/**",
        "*.log",
        ".git/**",
        "_deploy_hf.py",
        "_watch_hf.py",
        "_hf_logs.py",
        "_fix_hf.py",
        "_groq_models.py",
        "_verify_groq.py",
        "_test_*.py",
    ],
)
print(f"\nDONE → https://huggingface.co/spaces/{REPO_ID}")
