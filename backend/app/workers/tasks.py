"""
مهام Celery — غلاف رقيق حول خط المعالجة الموحّد
"""
from app.workers.celery_app import celery_app
from app.services.pipeline import run_pipeline


@celery_app.task(bind=True, name="process_lecture", max_retries=2, default_retry_delay=15)
def process_lecture(self, lecture_id: int):
    """معالجة محاضرة في الخلفية مع تحديث حالة Celery للتقدم الحي"""

    def on_progress(status: str, pct: int):
        self.update_state(state="PROGRESS", meta={"status": status, "progress": pct})

    result = run_pipeline(lecture_id, on_progress=on_progress)
    if result.get("status") == "failed":
        # لا نعيد المحاولة للأخطاء الدائمة (ملف تالف/فارغ)
        return result
    return result
