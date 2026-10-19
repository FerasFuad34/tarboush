import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api, { listLectures, deleteLecture, getHealth } from '../api/client'

export default function Home(){
  const navigate = useNavigate()
  const [demoBusy,setDemoBusy]=useState(false)
  const [demoError,setDemoError]=useState('')
  const [lectures,setLectures]=useState<any[]>([])
  const [health,setHealth]=useState<any>(null)
  const [loading,setLoading]=useState(true)

  const load=async()=>{
    try{
      const res = await listLectures()
      setLectures(res.data)
    }catch(e){ console.error(e)}
    setLoading(false)
  }
  useEffect(()=>{ load(); getHealth().then(r=>setHealth(r.data)).catch(()=>{}) },[])

  const statusColor=(s:string)=>{
    if(s==='done') return 'bg-green-100 text-green-700 border-green-200'
    if(s==='failed') return 'bg-red-100 text-red-700 border-red-200'
    if(s==='queued' || s==='transcribing' || s==='summarizing') return 'bg-amber-100 text-amber-700 border-amber-200 animate-pulse'
    return 'bg-slate-100 text-slate-600'
  }
  const statusLabel=(s:string)=>{
    const map:any={queued:'في الانتظار', transcribing:'جاري التفريغ...', summarizing:'جاري التلخيص...', glossary:'جاري القاموس...', quiz:'جاري الأسئلة...', done:'مكتملة', failed:'فشلت'}
    return map[s]||s
  }

  /** حجم مقروء: بايت/كيلوبايت/ميجابايت */
  const formatSize = (bytes:number)=>{
    if(!bytes) return '0 KB'
    if(bytes < 1024*1024) return `${(bytes/1024).toFixed(0)} KB`
    return `${(bytes/1024/1024).toFixed(2)} MB`
  }
  /** تاريخ عربي مقروء */
  const formatDate = (iso:string)=>{
    if(!iso) return ''
    const d = new Date(iso)
    return d.toLocaleString('ar-EG', {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'})
  }

  /** محاضرة تجريبية: يطلبها الخادم بمعالجة حقيقية ثم يفتح صفحتها */
  const startDemo=async()=>{
    setDemoBusy(true); setDemoError('')
    try{
      const res = await api.post('/api/v1/lectures/demo')
      navigate(`/lecture/${res.data.id}`)
    }catch(e:any){
      setDemoError(e.response?.data?.detail || 'تعذّر تشغيل المحاضرة التجريبية الآن')
    }
    setDemoBusy(false)
  }

  if(loading) return <div className="text-center py-20">جاري التحميل...</div>

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="bg-white rounded-2xl p-6 shadow border flex flex-col md:flex-row gap-6 items-center">
        <div className="flex-1">
          <h1 className="text-3xl font-bold text-[#7f1d1d]">مرحباً بك في طربوش 🎓</h1>
          <p className="text-slate-600 mt-2">ارفع محاضرتك (صوت/فيديو/PDF/PPTX/رابط يوتيوب) واحصل على: تفريغ دقيق + 3 مستويات تلخيص + قاموس + 10 أسئلة + تصدير PDF</p>
          <div className="mt-4 flex gap-3">
            <Link to="/upload" className="bg-[#7f1d1d] text-white px-6 py-3 rounded-xl font-bold hover:bg-[#991b1b]">+ رفع محاضرة جديدة</Link>
            <button onClick={startDemo} disabled={demoBusy}
              className="border border-[#7f1d1d] text-[#7f1d1d] px-6 py-3 rounded-xl font-bold hover:bg-orange-50 disabled:opacity-50">
              {demoBusy ? 'جاري التحضير...' : 'جرّب محاضرة تجريبية'}
            </button>
            <a href={`${api.defaults.baseURL}/docs`} target="_blank" rel="noreferrer" className="border px-6 py-3 rounded-xl">توثيق API</a>
          </div>
          {demoError && <div className="mt-3 text-sm bg-red-50 border border-red-200 text-red-800 rounded p-2">{demoError}</div>}
        </div>
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 text-sm min-w-[280px]">
          <div className="font-bold mb-2">حالة النظام</div>
          {health?.checks ? (
            <div className="space-y-1.5">
              {(['stt','ffmpeg','redis','ollama'] as const).map(k=>{
                const c = health.checks[k]
                if(!c) return null
                return (
                  <div key={k} className="flex items-center justify-between gap-2">
                    <span className={`inline-flex items-center gap-1 text-xs font-bold ${c.ok?'text-green-700':'text-amber-700'}`}>
                      <span className={`w-2 h-2 rounded-full ${c.ok?'bg-green-500':'bg-amber-500'}`}></span>
                      {c.label}
                    </span>
                    {!c.ok && <span className="text-[10px] text-slate-500 text-left flex-1">{c.detail}</span>}
                  </div>
                )
              })}
              <div className="text-xs text-slate-500 mt-2 pt-2 border-t border-orange-200">
                التفريغ: {health.config?.stt_provider} ({health.config?.stt_model}) • التلخيص: {health.config?.llm_provider}
              </div>
            </div>
          ): <div className="text-slate-500">جاري فحص النظام...</div>}
        </div>
      </div>

      {/* قائمة المحاضرات */}
      <div>
        <h2 className="font-bold text-lg mb-3">محاضراتي ({lectures.length})</h2>
        {lectures.length===0 ? (
          <div className="bg-white rounded-xl p-10 text-center border border-dashed">
            <div className="text-5xl mb-3">📚</div>
            <p>لا توجد محاضرات بعد. ابدأ برفع أول محاضرة لمدة 30 دقيقة.</p>
            <Link to="/upload" className="inline-block mt-4 bg-[#7f1d1d] text-white px-6 py-2 rounded-lg">رفع الآن</Link>
          </div>
        ): (
          <div className="grid md:grid-cols-2 gap-4">
            {lectures.map(l=>(
              <div key={l.id} className="bg-white rounded-xl p-4 shadow border hover:shadow-lg transition">
                <div className="flex justify-between items-start gap-2">
                  <div className="flex-1">
                    <div className="font-bold line-clamp-1">{l.title}</div>
                    <div className="text-xs text-slate-500">{l.filename} • {formatSize(l.file_size)} • {formatDate(l.created_at)}</div>
                  </div>
                  <span className={`text-xs px-3 py-1 rounded-full border font-bold ${statusColor(l.status)}`}>{statusLabel(l.status)} {l.progress?`${l.progress}%`:''}</span>
                </div>
                {l.status!=='done' && l.status!=='failed' && (
                  <div className="mt-3 w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                    <div className="bg-[#7f1d1d] h-2 transition-all" style={{width:`${l.progress||10}%`}}></div>
                  </div>
                )}
                {l.error && <div className="mt-2 text-xs bg-red-50 border border-red-200 rounded p-2 text-red-700">{l.error}</div>}
                <div className="mt-3 flex gap-2">
                  <Link to={`/lecture/${l.id}`} className="flex-1 bg-slate-900 text-white text-center py-2 rounded-lg text-sm font-bold hover:bg-black">فتح المحاضرة</Link>
                  <button onClick={async()=>{ if(confirm('حذف المحاضرة؟')){ await deleteLecture(l.id); load()}}} className="px-3 py-2 border rounded-lg text-sm hover:bg-red-50">حذف</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* دليل M1 */}
      <div className="bg-white rounded-xl p-5 border">
        <h3 className="font-bold">كيف أختبر M1 على محاضرة حقيقية (30 دقيقة)؟</h3>
        <ol className="list-decimal mr-6 mt-2 space-y-1 text-sm text-slate-700">
          <li>سجل محاضرة 30 دقيقة بالهاتف (MP3) أو استخدم ملف PDF لمادة عربية</li>
          <li>ارفعه عبر زر "رفع محاضرة" → ستظهر حالة "جاري التفريغ" مع نسبة مئوية حية</li>
          <li>بعد 2-4 دقائق (على CPU) ستتحول الحالة إلى "مكتملة" → افتحها لترى النص + الملخصات + القاموس + الأسئلة</li>
          <li>جرّب التصدير PDF/DOCX/Markdown وجرّب رفع نفس الملف مرة ثانية → سيخبرك "تم من قبل" (منع التكرار)</li>
          <li>افتح <a href="http://localhost:5555" target="_blank" className="text-[#7f1d1d] underline">Flower</a> لترى الطابور يعمل</li>
        </ol>
      </div>
    </div>
  )
}
