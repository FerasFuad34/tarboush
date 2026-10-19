# نشر طربوش على Render — دليل مختصر

> الهدف: رابط واحد تفتحه من أي جهاز وتجد المنصة جاهزة.
> الطريقة الموصى بها: **مستودع GitHub + خدمتان على Render** (API بايثون + واجهة ثابتة).

---

## 0) ما تحتاجه

| المتطلب | لماذا |
| :--- | :--- |
| حساب GitHub | لتخزين الكود (Render يسحبه من هناك) |
| حساب Render (موجود: `Feras's workspace`) | استضافة مجانية |
| توكن GitHub صالح | لإنشاء المستودع ورفع الملفات آلياً |

### كيف تصنع توكن GitHub صالحًا (دقيقة واحدة)

1. افتح: **https://github.com/settings/tokens?type=beta** (Fine-grained tokens).
2. **Generate new token** → الاسم: `tarboush-deploy` → Expiration: 7 أيام.
3. **Repository access:** `All repositories` (أو `Only select repositories` واختر المستودع بعد إنشائه).
4. **Permissions → Repository permissions:**
   - `Contents` = **Read and write**
   - `Administration` = **Read and write** (لإنشاء المستودع)
   - `Metadata` = Read (تُضاف تلقائياً)
5. **Generate token** وانسخه فوراً (يظهر مرة واحدة).

> ملاحظة مهمة: GitHub **يُلغي تلقائياً** أي توكن يُنشر في مكان عام. التوكن الذي أرسلته
> سابقاً يرجّع `401 Bad credentials` — يعني مُلغى أو منتهي. لا بأس، أنشئ واحداً جديداً.

---

## 1) النشر الآلي (سطر أوامر واحد)

```bash
export GH_TOKEN=github_pat_xxxxxxxx
export RND_TOKEN=rnd_xxxxxxxx
python scripts/deploy_to_render.py --repo tarboush --public
```

السيناريو الذي ينفّذه السكربت:

```
✅ GitHub: <login>
✅ أُنشئ المستودع: https://github.com/<login>/tarboush.git
✅ رُفع الكود إلى GitHub
✅ Render: Feras's workspace (tea-...)
✅ أُنشئت خدمة API: srv-...
   … tarboush-api: build_in_progress
   … tarboush-api: live
✅ tarboush-api يعمل: https://tarboush-api.onrender.com
✅ أُنشئت خدمة الواجهة
   … tarboush-web: live
🎉 المنصة جاهزة: https://tarboush-web.onrender.com
```

في النهاية يطبع السكربت **رابط المنصة** ورابط `/docs`.

---

## 2) النشر اليدوي (بدون سكربت)

1. ارفع المشروع إلى مستودع GitHub (أي طريقة: GitHub Desktop، `git push`، أو رفع الأرشيف).
2. في Render: **New → Blueprint** → اختر المستودع → سيقرأ `render.yaml` الموجود في الجذر.
3. بعد إنشاء الخدمتين، اضبط المتغيّرين التاليين من لوحة Render:
   - في `tarboush-api` → Environment → `CORS_ORIGINS` = رابط الواجهة (مثل `https://tarboush-web.onrender.com`).
   - في `tarboush-web` → Environment → `VITE_API_URL` = رابط الـ API (مثل `https://tarboush-api.onrender.com`).
4. أعد نشر الواجهة (Manual Deploy → Clear build cache & deploy) ليُبنى `VITE_API_URL` الجديد داخل الحزمة.

---

## 3) ما يعمل على Render المجاني — وما لا يعمل (بصراحة)

| الميزة | على Render (مجاني) | ملاحظة |
| :--- | :---: | :--- |
| رفع PDF / PPTX / DOCX / TXT / MD | ✅ | كل خط المعالجة النصية |
| تلخيص + قاموس + أسئلة | ✅ | استخراجي إن لم يوجد LLM |
| **تقسيم المواضيع + شرح يوتيوب/ويكيبيديا** | ✅ | يحتاج خروجاً للإنترنت (متاح) |
| بحث حر + زر تحديث المصادر | ✅ | |
| تصدير PDF/DOCX/MD/JSON/TXT | ✅ | |
| **تفريغ صوت/فيديو (faster-whisper)** | ❌ | الخطة المجانية 512MB وبلا ffmpeg |
| OCR لـ PDF ممسوح | ❌ | يحتاج tesseract في النظام |
| بقاء البيانات | ⚠️ | SQLite على قرص مؤقت → تُصفَّر عند كل نشر/إعادة تشغيل |
| سرعة الفتح الأول | ⚠️ | الخدمة المجانية تنام بعد 15 دقيقة خمول (~30-60 ثانية للاستيقاظ) |

**للتشغيل الكامل بالصوت على جهازك:** استخدم `docker-compose.yml` (فيه ffmpeg + whisper + Redis + Ollama).

---

## 4) بدائل إن تعذّر GitHub

| البديل | ملاحظة |
| :--- | :--- |
| نشر يدوي عبر لوحة Render من أرشيف ZIP | Render لا يقبل ZIP مباشرة؛ يحتاج مستودعاً أو صورة Docker |
| Docker image على أي سجل عام | يحتاج حساب سجل (Docker Hub) + بناء صورة |
| تشغيل محلي (ويندوز) | `دليل-التشغيل.md` — كامل الميزات بما فيها الصوت |

---

## 5) استكشاف الأخطاء

| العَرَض | السبب المحتمل | الحل |
| :--- | :--- | :--- |
| `401 Bad credentials` من GitHub | توكن مُلغى/منتهي/ناقص صلاحية | أنشئ توكناً جديداً بصلاحيتي Contents + Administration |
| Render: `repo not found` | المستودع خاص و Render GitHub App غير مفوَّض له | اجعل المستودع عاماً، أو فوّض التطبيق للمستودع من إعدادات Render |
| الواجهة تفتح لكن كل الطلبات تفشل | `VITE_API_URL` غير مضبوط وقت البناء | اضبطه ثم أعد النشر مع `Clear build cache` |
| `CORS error` في المتصفح | `CORS_ORIGINS` لا يحتوي رابط الواجهة | أضف الرابط ثم أعد تشغيل خدمة الـ API |
| بناء الواجهة يفشل | `npm ci` يحتاج `package-lock.json` | السكربت يستخدم `npm install` لهذا السبب |
