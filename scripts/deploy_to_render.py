"""
نشر طربوش على Render بضغطة واحدة (بعد توفّر توكن GitHub صالح).

ما يفعله بالترتيب:
  1) يتحقق من توكن GitHub.
  2) ينشئ مستودعاً (عام/خاص حسب ARG) ويرفع المشروع إليه.
  3) ينشئ خدمة API على Render (Python) وينتظر اكتمال النشر.
  4) ينشئ الواجهة (Static Site) ويربطها بعنوان الـ API.
  5) يضبط CORS على الـ API ليقبل الواجهة، ثم يطبع الرابط النهائي.

الاستخدام:
    export GH_TOKEN=...
    export RND_TOKEN=...
    python scripts/deploy_to_render.py --repo tarboush --public

ملاحظات صدق:
- الخطة المجانية في Render بذاكرة 512MB وبلا ffmpeg، لذلك التفريغ الصوتي (faster-whisper)
  غير متاح هناك؛ كل الميزات النصية والمصادر والتصدير تعمل. للتشغيل الكامل بالصوت استخدم
  docker-compose محلياً.
- قاعدة البيانات SQLite على قرص مؤقت: تُصفَّر عند كل إعادة نشر.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
GH = os.environ.get("GH_TOKEN", "").strip()
RND = os.environ.get("RND_TOKEN", "").strip()
GH_API = "https://api.github.com"
RND_API = "https://api.render.com/v1"


def die(msg: str, extra=None):
    print(f"❌ {msg}")
    if extra is not None:
        print(extra if isinstance(extra, str) else json.dumps(extra, ensure_ascii=False, indent=2))
    sys.exit(1)


def ok(msg: str):
    print(f"✅ {msg}")


# ---------------------------------------------------------------- GitHub
def gh_session() -> httpx.Client:
    return httpx.Client(
        base_url=GH_API,
        headers={
            "Authorization": f"Bearer {GH}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=60,
    )


def check_github() -> str:
    with gh_session() as c:
        r = c.get("/user")
    if r.status_code != 200:
        die("توكن GitHub غير صالح", r.text[:300])
    login = r.json()["login"]
    ok(f"GitHub: {login}")
    return login


def ensure_repo(login: str, name: str, public: bool) -> str:
    with gh_session() as c:
        r = c.get(f"/repos/{login}/{name}")
        if r.status_code == 200:
            clone = r.json()["clone_url"]
            ok(f"المستودع موجود: {clone}")
            return clone
        r = c.post("/user/repos", json={
            "name": name,
            "private": not public,
            "description": "طربوش — منصة عربية لتحويل المحاضرات إلى نص وملخصات ومصادر شرح",
            "auto_init": False,
        })
        if r.status_code not in (200, 201):
            die("تعذّر إنشاء المستودع (تحقق من صلاحية repo)", r.text[:400])
        clone = r.json()["clone_url"]
        ok(f"أُنشئ المستودع: {clone}")
        return clone


def push_repo(clone_url: str, login: str, public: bool) -> None:
    auth_url = clone_url.replace("https://", f"https://{login}:{GH}@")
    if not (ROOT / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.name", login], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", f"{login}@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "commit", "-m", "طربوش: منصة المحاضرات + الشرح والمصادر"],
                   cwd=ROOT, check=False)
    remotes = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if "origin" in remotes:
        subprocess.run(["git", "remote", "set-url", "origin", auth_url], cwd=ROOT, check=True)
    else:
        subprocess.run(["git", "remote", "add", "origin", auth_url], cwd=ROOT, check=True)
    res = subprocess.run(["git", "push", "-u", "origin", "main", "--force"], cwd=ROOT,
                         capture_output=True, text=True)
    if res.returncode != 0:
        die("فشل الرفع إلى GitHub", (res.stderr or res.stdout)[-600:])
    ok("رُفع الكود إلى GitHub")


# ---------------------------------------------------------------- Render
def rnd_session() -> httpx.Client:
    return httpx.Client(
        base_url=RND_API,
        headers={"Authorization": f"Bearer {RND}", "Accept": "application/json"},
        timeout=120,
    )


def get_owner() -> str:
    with rnd_session() as c:
        r = c.get("/owners")
    if r.status_code != 200:
        die("توكن Render غير صالح", r.text[:300])
    owner = r.json()[0]["owner"]
    ok(f"Render: {owner['name']} ({owner['id']})")
    return owner["id"]


def create_service(payload: dict) -> dict:
    with rnd_session() as c:
        r = c.post("/services", json=payload)
    if r.status_code not in (200, 201):
        die(f"تعذّر إنشاء خدمة {payload.get('name')}", r.text[:800])
    return r.json()["service"]


def wait_deploy(service_id: str, name: str, timeout: int = 900) -> str:
    """ينتظر انتهاء آخر نشر ويعيد رابط الخدمة"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        with rnd_session() as c:
            d = c.get(f"/services/{service_id}/deploys", params={"limit": 1})
            s = c.get(f"/services/{service_id}")
        if d.status_code == 200 and d.json():
            dep = d.json()[0]["deploy"]
            status = dep.get("status")
            print(f"   … {name}: {status} ({int(time.time() - t0)}ث)", flush=True)
            if status == "live":
                url = s.json()["service"].get("serviceDetails", {}).get("url") or dep.get("url")
                ok(f"{name} يعمل: {url}")
                return url
            if status in ("build_failed", "update_failed", "canceled", "pre_deploy_failed"):
                die(f"فشل نشر {name}", json.dumps(dep, ensure_ascii=False)[:800])
        time.sleep(15)
    die(f"انتهت مهلة انتظار {name}")


def set_env(service_id: str, vars_: dict) -> None:
    with rnd_session() as c:
        cur = c.get(f"/services/{service_id}/env-vars")
        existing = {e["envVar"]["key"]: e["envVar"]["value"] for e in cur.json()} if cur.status_code == 200 else {}
        existing.update(vars_)
        payload = [{"key": k, "value": v} for k, v in existing.items()]
        r = c.put(f"/services/{service_id}/env-vars", json=payload)
    if r.status_code not in (200, 201):
        print(f"⚠️ تعذّر تحديث متغيرات البيئة: {r.text[:300]}")
    else:
        ok(f"حُدِّثت متغيرات البيئة: {', '.join(vars_)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="tarboush")
    ap.add_argument("--public", action="store_true", help="مستودع عام (أسهل لنشر Render)")
    ap.add_argument("--api-name", default="tarboush-api")
    ap.add_argument("--web-name", default="tarboush-web")
    args = ap.parse_args()

    if not GH or not RND:
        die("ضع GH_TOKEN و RND_TOKEN في البيئة أولاً")

    login = check_github()
    clone = ensure_repo(login, args.repo, args.public)
    push_repo(clone, login, args.public)
    owner = get_owner()

    repo_url = clone.removesuffix(".git")

    api = create_service({
        "type": "web_service",
        "name": args.api_name,
        "ownerId": owner,
        "repo": repo_url,
        "branch": "main",
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "python",
            "plan": "free",
            "region": "frankfurt",
            "healthCheckPath": "/health",
            "envSpecificDetails": {
                "buildCommand": "pip install --upgrade pip && pip install -r backend/requirements-render.txt",
                "startCommand": "cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT",
            },
            "envVars": [
                {"key": "PYTHON_VERSION", "value": "3.12.6"},
                {"key": "DATABASE_URL", "value": "sqlite:///./storage/tarboush.db"},
                {"key": "STORAGE_PATH", "value": "./storage/uploads"},
                {"key": "EXPORT_PATH", "value": "./storage/exports"},
                {"key": "RESOURCES_ENABLED", "value": "true"},
                {"key": "RESOURCE_PROVIDERS", "value": "youtube,wikipedia,wikiversity,wikibooks,arxiv"},
                {"key": "MAX_UPLOAD_SIZE_MB", "value": "25"},
                {"key": "SECRET_KEY", "value": os.urandom(32).hex()},
                {"key": "CORS_ORIGINS", "value": "http://localhost:5173"},
            ],
        },
    })
    ok(f"أُنشئت خدمة API: {api['id']}")
    api_url = wait_deploy(api["id"], args.api_name)

    web = create_service({
        "type": "web_service",
        "name": args.web_name,
        "ownerId": owner,
        "repo": repo_url,
        "branch": "main",
        "autoDeploy": "yes",
        "serviceDetails": {
            "env": "static",
            "plan": "free",
            "buildCommand": "cd frontend && npm install && npm run build",
            "staticPublishPath": "frontend/dist",
            "envVars": [{"key": "VITE_API_URL", "value": api_url}],
            "routes": [{"type": "rewrite", "source": "/*", "destination": "/index.html"}],
        },
    })
    ok(f"أُنشئت خدمة الواجهة: {web['id']}")
    web_url = wait_deploy(web["id"], args.web_name)

    set_env(api["id"], {"CORS_ORIGINS": f"{web_url},http://localhost:5173"})

    print("\n" + "=" * 62)
    print(f"🎉 المنصة جاهزة: {web_url}")
    print(f"   API:         {api_url}")
    print(f"   التوثيق:     {api_url}/docs")
    print("=" * 62)
    print("ملاحظة: الخطة المجانية تُنيم الخدمة بعد 15 دقيقة خمول،")
    print("       وأول فتح بعدها يستغرق ~30-60 ثانية.")


if __name__ == "__main__":
    main()
