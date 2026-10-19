import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api/client'
import TopicSources from '../components/TopicSources'

export default function Lecture(){
  const {id}=useParams()
  const [data,setData]=useState<any>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [activeTab,setActiveTab]=useState('topics')
  const [quizAnswers,setQuizAnswers]=useState<Record<number,number>>({})
  const [showScore,setShowScore]=useState(false)

  const load=async()=>{
    try{
      const res = await api.get(`/api/v1/lectures/${id}`)
      setData(res.data)
    }catch(e:any){ setError(e.response?.data?.detail||e.message)}
    setLoading(false)
  }

  useEffect(()=>{
    load()
    // polling كل ثانيتين إذا لم تكتمل
    const interval = setInterval(async()=>{
      try{
        const res = await api.get(`/api/v1/lectures/${id}/progress`)
        if(res.data.status==='done' || res.data.status==='failed'){
          clearInterval(interval); load()
        } else {
          setData((prev:any)=> prev ? {...prev, status: res.data.status, progress: res.data.progress} : prev)
        }
      }catch{}
    },2000)
    return ()=>clearInterval(interval)
  },[id])

  /** إعادة المعالجة (force=true حتى لو كانت مكتملة) */
  const retry=async(force=false)=>{
    if(force && !confirm('إعادة معالجة المحاضرة من جديد؟ سيتم استبدال النص والملخصات والأسئلة الحالية.')) return
    await api.post(`/api/v1/lectures/${id}/retry${force?'?force=true':''}`)
    setData({...data, status:'queued', progress:0, error:null})
  }

  /** تسميات عربية لحالة المحاضرة (بدل إظهار قيم قاعدة البيانات الخام) */
  const STATUS_LABELS: Record<string,string> = {
    queued: 'في الانتظار',
    transcribing: 'جاري التفريغ',
    summarizing: 'جاري التلخيص',
    glossary: 'جاري استخراج المصطلحات',
    quiz: 'جاري توليد الأسئلة',
    done: 'مكتملة',
    failed: 'فشلت',
  }

  const [speed,setSpeed] = useState(1)
  const audioPlayer = useRef<HTMLAudioElement|null>(null)

  /** تنسيق الثواني إلى mm:ss */
  const fmt = (sec:number)=>{
    const m = Math.floor((sec||0)/60), s2 = Math.floor((sec||0)%60)
    return `${m}:${String(s2).padStart(2,'0')}`
  }
  /** الانتقال إلى ثانية محددة في المشغل */
  const seekTo = (sec:number)=>{
    const el = audioPlayer.current
    if(!el) return
    el.currentTime = Math.max(0, sec)
    el.play().catch(()=>{})
    el.scrollIntoView({behavior:'smooth', block:'center'})
  }
  /** تغيير سرعة التشغيل 0.75x - 2.5x */
  const changeSpeed = (v:number)=>{
    setSpeed(v)
    if(audioPlayer.current) audioPlayer.current.playbackRate = v
  }

  if(loading) return <div className="text-center py-20">جاري تحميل المحاضرة...</div>
  if(error) return <div className="bg-red-50 border border-red-200 p-6 rounded-xl">خطأ: {error}</div>
  if(!data) return null

  const isDone = data.status==='done'
  const isFailed = data.status==='failed'
  const isProcessing = !isDone && !isFailed

  const score = ()=>{
    if(!data.quiz) return 0
    let s=0
    data.quiz.questions.forEach((q:any,i:number)=>{ if(quizAnswers[i]===q.answer) s++ })
    return s
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white rounded-xl p-5 shadow border">
        <div className="flex flex-wrap justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold">{data.title}</h1>
            <div className="text-xs text-slate-500">{data.filename} • {new Date(data.created_at).toLocaleString('ar-YE')}</div>
            <div className={`inline-block mt-2 text-xs px-3 py-1 rounded-full border font-bold ${isDone?'bg-green-100 text-green-700':isFailed?'bg-red-100 text-red-700':'bg-amber-100 text-amber-700 animate-pulse'}`}>
              {STATUS_LABELS[data.status] || data.status} {data.progress ? `${data.progress}%` : ''}
            </div>
          </div>
          <div className="flex gap-2 self-start">
            <Link to="/" className="border px-4 py-2 rounded-lg text-sm">← العودة</Link>
            <button onClick={()=>retry(isDone)} className="bg-amber-600 text-white px-4 py-2 rounded-lg text-sm font-bold hover:bg-amber-700">
              {isFailed ? 'إعادة المحاولة' : 'إعادة المعالجة'}
            </button>
          </div>
        </div>
        {isProcessing && (
          <div className="mt-4">
            <div className="w-full bg-slate-100 rounded-full h-3 overflow-hidden">
              <div className="bg-[#7f1d1d] h-3 transition-all" style={{width:`${data.progress||5}%`}}></div>
            </div>
            <p className="text-xs text-slate-600 mt-2">جاري المعالجة في الخلفية (تفريغ → تلخيص → قاموس → أسئلة). يمكنك البقاء هنا أو العودة لاحقاً - لن يضيع التقدم.</p>
          </div>
        )}
        {isFailed && <div className="mt-3 bg-red-50 border border-red-200 rounded p-3 text-sm text-red-800">❌ {data.error}</div>}
      </div>

      {/* شريط المشغل: يبقى ظاهراً في كل التبويبات حتى تعمل الطوابع الزمنية دائماً */}
      {isDone && data.is_media && (
        <div className="bg-white rounded-xl p-4 shadow border sticky top-[64px] z-40">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-bold text-[#7f1d1d]">مشغل المحاضرة</span>
            <audio
              ref={audioPlayer}
              controls
              preload="metadata"
              className="flex-1 min-w-[240px]"
              src={`${api.defaults.baseURL}/api/v1/lectures/${id}/media`}
            />
            <div className="flex items-center gap-1">
              <span className="text-xs text-slate-500">السرعة</span>
              {[0.75,1,1.25,1.5,2,2.5].map(v=>(
                <button key={v} onClick={()=>changeSpeed(v)}
                  className={`px-2 py-1 rounded border text-xs font-bold ${speed===v?'bg-[#7f1d1d] text-white border-[#7f1d1d]':'hover:bg-slate-50'}`}>
                  {v}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {!isDone ? (
        <div className="bg-white rounded-xl p-10 text-center border">
          <div className="text-5xl mb-4">⏳</div>
          <p>المحاضرة قيد المعالجة... يحدث التقدم كل ثانيتين تلقائياً</p>
          <p className="text-xs text-slate-500 mt-2">محاضرة 30 دقيقة تستغرق 2-4 دقائق على CPU (medium) أو أقل على GPU</p>
        </div>
      ):(
        <>
          {/* Tabs */}
          <div className="bg-white rounded-xl shadow border overflow-hidden">
            <div className="flex overflow-x-auto border-b text-sm">
              {[
                ['topics','الشرح والمصادر'],
                ['transcript','النص الكامل'],
                ['summaries','الملخصات'],
                ['glossary','القاموس'],
                ['quiz','الاختبار'],
                ['export','تصدير ومشاركة'],
              ].map(([k,l])=>(
                <button key={k} onClick={()=>setActiveTab(k)} className={`px-5 py-3 whitespace-nowrap border-b-2 font-bold ${activeTab===k?'border-[#7f1d1d] text-[#7f1d1d] bg-orange-50':'border-transparent hover:bg-slate-50'}`}>{l}</button>
              ))}
            </div>
            <div className="p-6">
              {activeTab==='topics' && (
                <TopicSources
                  topics={data.topics || []}
                  lectureId={id}
                  isMedia={!!data.is_media}
                  onSeek={seekTo}
                  onChanged={load}
                />
              )}

              {activeTab==='transcript' && (
                <div className="space-y-4">
                  {data.is_media && data.transcript?.segments?.length>0 && (
                    <div className="bg-slate-50 border rounded-lg p-3 text-xs">
                      <div className="font-bold mb-2">الطوابع الزمنية — اضغط أي مقطع للانتقال إليه في المشغل:</div>
                      <div className="flex flex-wrap gap-2 max-h-40 overflow-auto">
                        {data.transcript.segments.map((s:any,i:number)=>(
                          <button key={i} onClick={()=>seekTo(s.start)} className="bg-white border rounded px-2 py-1 hover:bg-orange-50 text-right">
                            <span className="font-bold text-[#7f1d1d] ltr inline-block">[{fmt(s.start)}]</span> {s.text.slice(0,70)}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {!data.is_media && (
                    <div className="bg-slate-50 border rounded-lg p-3 text-xs text-slate-600">
                      هذا ملف نصي (PDF/Word/نص) — لا يوجد صوت للانتقال الزمني، لكن يمكنك نسخ أي فقرة أو اقتباسها.
                    </div>
                  )}
                  <div className="bg-white border rounded-lg p-4 leading-8 whitespace-pre-wrap max-h-[60vh] overflow-auto">{data.transcript?.text || 'لا يوجد نص'}</div>
                  <div className="text-xs text-slate-500">عدد الكلمات: {data.transcript?.word_count}</div>
                </div>
              )}

              {activeTab==='summaries' && (
                <div className="space-y-4">
                  {data.summaries?.length===0 && <p>لا توجد ملخصات</p>}
                  {data.summaries?.map((s:any)=>(
                    <div key={s.id} className="border rounded-xl p-4 bg-orange-50/30">
                      <div className="font-bold text-[#7f1d1d] mb-2">
                        {s.level==='glimpse'?'لمحة سريعة (50 كلمة)': s.level==='bullets'?'نقاط مرتبة': s.level==='page'?'ملخص صفحة متكاملة': s.level==='top10'?'أهم 10 أفكار':'ملخص'}
                      </div>
                      <div className="whitespace-pre-wrap leading-7 text-sm">{s.content}</div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab==='glossary' && (
                <div>
                  {data.glossary?.length===0 ? <p>لا توجد مصطلحات</p> : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm border">
                        <thead className="bg-slate-900 text-white"><tr><th className="p-2">المصطلح العربي</th><th className="p-2">الإنجليزي</th><th className="p-2">التعريف من سياق المحاضرة</th></tr></thead>
                        <tbody>{data.glossary.map((g:any)=><tr key={g.id} className="border-t hover:bg-orange-50"><td className="p-2 font-bold">{g.term_ar}</td><td className="p-2 ltr">{g.term_en}</td><td className="p-2">{g.definition}</td></tr>)}</tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {activeTab==='quiz' && (
                <div className="space-y-4">
                  {!data.quiz ? <p>لا يوجد اختبار</p> : (
                    <>
                      {data.quiz.questions.map((q:any,i:number)=>(
                        <div key={i} className="border rounded-xl p-4">
                          <div className="font-bold">س{i+1}: {q.question}</div>
                          <div className="mt-3 space-y-2">
                            {q.options.map((opt:string,j:number)=>(
                              <label key={j} className={`flex gap-2 p-2 rounded-lg border cursor-pointer ${quizAnswers[i]===j?'bg-[#7f1d1d] text-white border-[#7f1d1d]':'hover:bg-slate-50'}`}>
                                <input type="radio" name={`q${i}`} checked={quizAnswers[i]===j} onChange={()=>setQuizAnswers({...quizAnswers,[i]:j})} className="mt-1"/>
                                <span className="text-sm">{opt}</span>
                              </label>
                            ))}
                          </div>
                          {showScore && (
                            <div className={`mt-3 p-3 rounded-lg text-sm ${quizAnswers[i]===q.answer?'bg-green-50 border border-green-200 text-green-800':'bg-red-50 border border-red-200 text-red-800'}`}>
                              {quizAnswers[i]===q.answer ? '✅ إجابة صحيحة' : `❌ خطأ - الصحيحة: ${q.options[q.answer]}`}
                              <div className="mt-1 text-xs opacity-80">الشرح: {q.explanation}</div>
                              {q.source_quote && <div className="text-xs mt-1 italic">اقتباس: "{q.source_quote}"</div>}
                            </div>
                          )}
                        </div>
                      ))}
                      <div className="flex gap-3">
                        <button onClick={()=>setShowScore(true)} className="bg-[#7f1d1d] text-white px-6 py-3 rounded-xl font-bold">تصحيح وإظهار الدرجة</button>
                        {showScore && <div className="self-center font-bold">نتيجتك: {score()} / {data.quiz.questions.length}</div>}
                      </div>
                    </>
                  )}
                </div>
              )}

              {activeTab==='export' && (
                <div className="space-y-4">
                  <p className="text-sm text-slate-600">صدّر كل شيء بضغطة واحدة. PDF بخط عربي مضمن، DOCX للطباعة، Markdown للـ Notion، JSON للمطورين.</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {[
                      ['pdf','تصدير PDF','bg-red-600'],
                      ['docx','تصدير Word','bg-blue-600'],
                      ['markdown','تصدير Markdown','bg-slate-800'],
                      ['json','تصدير JSON','bg-green-600'],
                      ['txt','تصدير TXT','bg-slate-600'],
                    ].map(([fmt,label,color])=>(
                      <a key={fmt} href={`${api.defaults.baseURL}/api/v1/lectures/${id}/export/${fmt}`} target="_blank" className={`${color} text-white text-center py-3 rounded-xl font-bold hover:opacity-90`}>{label}</a>
                    ))}
                  </div>
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm">
                    <b>رابط المشاركة (M4):</b> سيضاف هنا رابط عام/مقيّد بكلمة مرور. حالياً استخدم التصدير والمشاركة اليدوية.
                  </div>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
