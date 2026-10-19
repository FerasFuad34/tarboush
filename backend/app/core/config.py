"""
إعدادات طربوش - مركزية وآمنة
كل القيم تُقرأ من .env ولا توجد مفاتيح في الواجهة
"""
from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    app_name: str = "طربوش"
    app_env: str = "development"
    secret_key: str = "change-me"
    
    database_url: str = "sqlite:///./storage/tarboush.db"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/0"
    
    storage_path: str = "./storage/uploads"
    export_path: str = "./storage/exports"
    
    stt_enabled: bool = True  # False = نشر نصّي فقط (بلا صوت) كما في خطة Render المجانية
    stt_provider: str = "local_whisper"  # local_whisper | groq
    stt_model: str = "medium"
    whisper_model_dir: str = "./storage/models"
    groq_api_key: str = ""
    groq_stt_model: str = "whisper-large-v3-turbo"
    
    llm_provider: str = "ollama"  # ollama | groq | openai
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen2.5:7b"
    openai_api_key: str = ""
    groq_llm_api_key: str = ""
    
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    
    jwt_secret: str = "change-jwt"
    jwt_expire_minutes: int = 1440
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    
    whisper_beam_size: int = 5
    whisper_language: str = "ar"
    enable_deduplication: bool = True

    # === الحجم: 0 = بلا حد مطلق (الحجم يُحدَّد حسب المحاضرة نفسها) ===
    # عند 0 يرفض النظام الملف فقط إذا نفدت مساحة القرص.
    max_upload_size_mb: int = 0
    # تفريغ المحاضرات الطويلة على أجزاء لتقليل استهلاك الذاكرة (ثانية)
    audio_chunk_seconds: int = 900
    # تنقية الصوت قبل التفريغ (إزالة ضجيج القاعة)
    enable_denoise: bool = True

    # === ربط المصادر التعليمية ===
    resource_providers: str = "youtube,wikipedia,wikiversity,wikibooks,arxiv"
    youtube_results_per_topic: int = 3
    wiki_results_per_topic: int = 2
    resource_search_timeout: float = 15.0
    resources_enabled: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"

settings = Settings()

# إنشاء المجلدات إن لم تكن موجودة
os.makedirs(settings.storage_path, exist_ok=True)
os.makedirs(settings.export_path, exist_ok=True)
os.makedirs("./storage", exist_ok=True)
