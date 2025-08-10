# github_sync.py
import os, base64, json
from pathlib import Path
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

TOKEN  = os.getenv("GITHUB_TOKEN")
OWNER  = os.getenv("GITHUB_OWNER")
REPO   = os.getenv("GITHUB_REPO")
PATH   = os.getenv("GITHUB_DB_PATH", "budget.db")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

API = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{PATH}"

def _headers():
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return {"Authorization": f"token {TOKEN}",
            "Accept": "application/vnd.github+json"}

def download_db(dest: Path) -> str | None:
    """Скачать budget.db в dest. Вернёт sha (или None, если файла ещё нет в репо)."""
    r = requests.get(API, headers=_headers(), params={"ref": BRANCH})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    content = base64.b64decode(data["content"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return data.get("sha")

def upload_db(src: Path, sha: str | None, message: str = "Update budget.db") -> str:
    """Выгрузить файл в репо. Если sha None — создаст файл, иначе обновит с проверкой версии."""
    content_b64 = base64.b64encode(src.read_bytes()).decode()
    payload = {"message": message, "content": content_b64, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    r = requests.put(API, headers=_headers(), data=json.dumps(payload))
    if r.status_code == 409:
        # удалённая версия изменилась: надо скачать заново и повторить по логике приложения
        raise RuntimeError("Remote has changed (409). Pull latest and retry.")
    r.raise_for_status()
    return r.json()["content"]["sha"]