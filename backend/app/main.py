"""
طربوش - FastAPI الرئيسي
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os

from app.core.config import settings
from app.core.database import init_db
from app.api.v1.lectures import router as lectures_router

app = FastAPI(
    title="طربوش - منصة المحاضرات الذكية",
    description="تحويل المحاضرات إلى ملخصات وأسئلة ومواد دراسة - PWA + RTL",
    version="1.0.0-M1",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS للواجهة
origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins + ["*"],  # للسماح في التطوير
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# إنشاء الجداول عند الاستيراد (مضمون في كل بيئة: uvicorn / celery / اختبارات)
# create_all آمنة التكرار (checkfirst=True افتراضياً) فلا تُنشئ مرتين.
init_db()


@app.on_event("startup")
async def startup():
    # تأكيد إضافي: لو حُذف ملف قاعدة البيانات أثناء التشغيل
    init_db()
    print("✅ طربوش جاهز - http://localhost:8000/docs")
    print(f"   STT: {settings.stt_provider} | LLM: {settings.llm_provider} | DB: {settings.database_url}")

# Routes
app.include_router(lectures_router, prefix="/api/v1")

@app.get("/")
def root():
    return {
        "name": "طربوش",
        "version": "1.0.0-M1",
        "status": "يعمل ✅",
        "docs": "/docs",
        "frontend": settings.cors_origins
    }

@app.get("/health")
def health():
    """
    فحص صحة النظام — يرجّع لكل خدمة: ok (منطقي) + label عربي قصير + detail تقني
    الواجهة تعتمد على ok/label لتلوين الشارة بدون أي تحليل نصي هش.
    """
    checks = {}

    # Redis (الطابور)
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1.5)
        r.ping()
        checks["redis"] = {"ok": True, "label": "Redis متصل", "detail": ""}
    except Exception:
        checks["redis"] = {
            "ok": False,
            "label": "Redis غير متصل",
            "detail": "سيعمل النظام في الوضع المتزامن (خيط خلفي) بدل الطابور",
        }

    # Ollama (التلخيص الذكي)
    try:
        import httpx
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        ok = resp.status_code == 200
        checks["ollama"] = {
            "ok": ok,
            "label": "Ollama متصل" if ok else "Ollama غير متاح",
            "detail": "" if ok else "سيُستخدم التلخيص الاستخراجي المحلي البسيط",
        }
    except Exception:
        checks["ollama"] = {
            "ok": False,
            "label": "Ollama غير متاح",
            "detail": "سيُستخدم التلخيص الاستخراجي المحلي البسيط",
        }

    # faster-whisper
    if not settings.stt_enabled:
        checks["stt"] = {
            "ok": True,
            "label": "التفريغ الصوتي معطّل (وضع النصوص فقط)",
            "detail": "STT_ENABLED=false — الملفات النصية وPDF/PPTX/DOCX تعمل بالكامل",
        }
    else:
        try:
            import faster_whisper  # noqa: F401  (فحص توفر المكتبة فقط)
            checks["stt"] = {"ok": True, "label": "محرك التفريغ جاهز", "detail": settings.stt_model}
        except Exception:
            checks["stt"] = {"ok": False, "label": "محرك التفريغ غير مثبت", "detail": "ثبّت faster-whisper"}

    # ffmpeg (مطلوب لكل صوت/فيديو)
    import shutil
    has_ffmpeg = shutil.which("ffmpeg") is not None
    if not settings.stt_enabled:
        checks["ffmpeg"] = {"ok": True, "label": "ffmpeg غير مطلوب (لا صوت)", "detail": ""}
    else:
        checks["ffmpeg"] = {
            "ok": has_ffmpeg,
            "label": "ffmpeg جاهز" if has_ffmpeg else "ffmpeg غير مثبت",
            "detail": "" if has_ffmpeg else "لازم لاستخراج الصوت من الفيديو وتنظيفه",
        }

    # مصادر الشرح الخارجية (اختيارية: تعطّلها لا يمنع المنصة من العمل)
    try:
        from app.services.resources import PROVIDERS
        enabled = [p.strip() for p in (settings.resource_providers or "").split(",") if p.strip()]
        enabled = [p for p in enabled if p in PROVIDERS]
        checks["resources"] = {
            "ok": bool(enabled) and settings.resources_enabled,
            "label": f"{len(enabled)} مزوّد للشرح الخارجي" if enabled and settings.resources_enabled else "الربط الخارجي معطّل",
            "detail": ", ".join(enabled) if enabled else "RESOURCES_ENABLED=false أو لا مزودين",
        }
    except Exception as e:  # noqa: BLE001
        checks["resources"] = {"ok": False, "label": "مزوّدات المصادر غير متاحة", "detail": type(e).__name__}

    critical_ok = checks["stt"]["ok"] and checks["ffmpeg"]["ok"]
    return {
        "status": "healthy" if critical_ok and checks["redis"]["ok"] else ("degraded" if critical_ok else "unhealthy"),
        "checks": checks,
        "config": {
            "stt_provider": settings.stt_provider,
            "stt_model": settings.stt_model,
            "llm_provider": settings.llm_provider,
            "storage": settings.storage_path,
            "max_upload_size_mb": settings.max_upload_size_mb,
            "resource_providers": settings.resource_providers,
        },
    }

# تقديم ملفات التصدير
if os.path.exists(settings.export_path):
    app.mount("/exports", StaticFiles(directory=settings.export_path), name="exports")

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """إرجاع رسائل HTTP الأصلية كما هي (404/400/413...) بدل تحويلها لخطأ داخلي"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def global_exception(request, exc):
    """التقاط أي خطأ غير متوقع برسالة عربية دون كشف تفاصيل حساسة"""
    print(f"[Unhandled] {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "حدث خطأ غير متوقع. أعد المحاولة، وإن تكرر راجع /health", "hint": str(exc)[:200]}
    )
