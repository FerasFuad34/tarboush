import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

/** حدود الرفع المجزّأ: كل ما فوق 20MB يُرفع على قطع (فيديو/صوت طويل) */
const CHUNK = 8 * 1024 * 1024
const CHUNK_THRESHOLD = 20 * 1024 * 1024

export default function Upload(){
  const [file,setFile]=useState<File|null>(null)
  const [title,setTitle]=useState('')
  const [youtube,setYoutube]=useState('')
  const [progress,setProgress]=useState(0)
  const [msg,setMsg]=useState('')
  const [error,setError]=useState('')
  const [recording,setRecording]=useState(false)
  const [elapsed,setElapsed]=useState(0)
  const mediaRef = useRef<MediaRecorder|null>(null)
  const timerRef = useRef<number|null>(null)
  const navigate = useNavigate()

  useEffect(()=>()=>{ if(timerRef.current) window.clearInterval(timerRef.current) },[])

  /* ---------------------------------------------------------------- رفع */
  const uploadChunked = async (f: File) => {
    const init = await api.post('/api/v1/lectures/upload/init', (()=>{
      const fd = new FormData()
      fd.append('filename', f.name)
      fd.append('size', String(f.size))
      if(title) fd.append('title', title)
      return fd
    })())
    const uploadId = init.data.upload_id
    const total = Math.ceil(f.size / CHUNK)
    let sent = 0

    for(let i=0;i<total;i++){
      const slice = f.slice(i*CHUNK, Math.min((i+1)*CHUNK, f.size))
      const fd = new FormData()
      fd.append('upload_id', uploadId)
      fd.append('index', String(i))
      fd.append('chunk', slice, f.name)
      // إعادة محاولة القطعة نفسها عند انقطاع الشبكة
      for(let attempt=0; attempt<4; attempt++){
        try{
          await api.post('/api/v1/lectures/upload/chunk', fd, {
            headers:{'Content-Type':'multipart/form-data'},
            timeout: 0,
          })
          break
        }catch(e){
          if(attempt===3) throw e
          await new Promise(r=>setTimeout(r, 1200*(attempt+1)))
        }
      }
      sent += slice.size
      setProgress(Math.round(sent*100/f.size))
    }

    const fd = new FormData()
    fd.append('upload_id', uploadId)
    return api.post('/api/v1/lectures/upload/complete', fd, { timeout: 0 })
  }

  const doUpload=async()=>{
    if(!file){ setError('اختر ملفاً أولاً'); return }
    setError(''); setMsg('جاري الرفع...'); setProgress(1)
    try{
      let res
      if(file.size > CHUNK_THRESHOLD){
        res = await uploadChunked(file)
      }else{
        const fd = new FormData()
        fd.append('file', file)
        if(title) fd.append('title', title)
        res = await api.post('/api/v1/lectures/upload', fd, {
          headers:{'Content-Type':'multipart/form-data'},
          timeout: 0,
          onUploadProgress:(e)=>{ if(e.total) setProgress(Math.round(e.loaded*100/e.total)) }
        })
      }
      setMsg(res.data.deduplicated
        ? 'هذا الملف موجود مسبقاً — أعدنا لك المحاضرة نفسها ✅'
        : 'تم الرفع! جاري التحليل في الخلفية...')
      setTimeout(()=> navigate(`/lecture/${res.data.id}`), 800)
    }catch(err:any){
      setError(err.response?.data?.detail || 'فشل الرفع: '+err.message)
      setProgress(0)
    }
  }

  /* ------------------------------------------------------------ يوتيوب */
  const doYoutube=async()=>{
    if(!youtube.includes('youtube') && !youtube.includes('youtu.be')){ setError('رابط YouTube غير صالح'); return }
    setError(''); setMsg('جاري تحميل الفيديو من YouTube... قد يستغرق دقيقة')
    try{
      const fd = new FormData()
      fd.append('url', youtube)
      if(title) fd.append('title', title)
      const res = await api.post('/api/v1/lectures/transcribe_youtube', fd)
      setMsg('تم الإرسال! جاري التفريغ...')
      setTimeout(()=> navigate(`/lecture/${res.data.id}`), 800)
    }catch(err:any){ setError(err.response?.data?.detail || err.message)}
  }

  /* ------------------------------------------------------------- تسجيل */
  const startRecord=async()=>{
    try{
      const stream = await navigator.mediaDevices.getUserMedia({
        audio:{ echoCancellation:true, noiseSuppression:true, autoGainControl:true }
      })
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm'
      const mr = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 48000 })
      const chunks:Blob[]=[]
      mr.ondataavailable=e=>{ if(e.data.size) chunks.push(e.data) }
      mr.onstop=()=>{
        const blob = new Blob(chunks, {type:'audio/webm'})
        const f = new File([blob], `تسجيل_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.webm`, {type:'audio/webm'})
        setFile(f)
        setMsg(`تم التسجيل (${fmt(elapsed)}) — جاهز للرفع، اضغط «رفع ومعالجة»`)
        stream.getTracks().forEach(t=>t.stop())
      }
      mediaRef.current=mr
      // كل 30 ثانية تُحفظ قطعة — تسجيل طويل لا يضيع إن تعطّل المتصفح
      mr.start(30000)
      setRecording(true); setElapsed(0)
      timerRef.current = window.setInterval(()=> setElapsed(v=>v+1), 1000)
      setMsg('جاري التسجيل... لا يوجد حد للمدة (محاضرة كاملة ساعة تعمل)')
    }catch(e:any){ setError('الميكروفون غير متاح: '+e.message)}
  }

  const stopRecord=()=>{
    if(mediaRef.current && mediaRef.current.state!=='inactive'){
      mediaRef.current.stop()
    }
    if(timerRef.current) window.clearInterval(timerRef.current)
    setRecording(false)
  }

  const fmt=(s:number)=>`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">رفع محاضرة جديدة</h1>
      <p className="text-slate-600 text-sm">
        أي صيغة، أي تخصص، بلا حد للحجم أو المدة: فيديو محاضرة، تسجيل صوتي، PDF، Word، PowerPoint،
        Excel، صور، حتى ملف مضغوط. النوع يُحدَّد من محتوى الملف نفسه.
      </p>

      {/* رفع ملف */}
      <div className="bg-white rounded-xl p-6 shadow border">
        <h3 className="font-bold mb-3">1) رفع ملف من جهازك</h3>
        <input type="text" placeholder="عنوان المحاضرة (اختياري) — يُستخدم كتلميح لتحسين دقة التفريغ"
               value={title} onChange={e=>setTitle(e.target.value)}
               className="w-full border rounded-lg px-3 py-2 mb-3"/>
        <div
          className="border-2 border-dashed rounded-xl p-6 text-center bg-orange-50/50"
          onDragOver={e=>e.preventDefault()}
          onDrop={e=>{ e.preventDefault(); const f=e.dataTransfer.files?.[0]; if(f) setFile(f) }}
        >
          {/* بلا accept: كل الصيغ متاحة في نافذة الاختيار */}
          <input type="file" id="file" onChange={e=>setFile(e.target.files?.[0]||null)} className="hidden"/>
          <label htmlFor="file" className="cursor-pointer block">
            <div className="text-4xl mb-2">📁</div>
            <div className="font-bold text-[#7f1d1d]">اضغط لاختيار أي ملف</div>
            <div className="text-xs text-slate-500 mt-1">أو اسحب الملف هنا — بلا قيود على الصيغة أو الحجم</div>
          </label>
          {file && <div className="mt-3 text-sm bg-white border rounded p-2">
            المحدد: <b>{file.name}</b> — {(file.size/1024/1024).toFixed(2)} MB
            {file.size > CHUNK_THRESHOLD && <span className="text-emerald-700"> (رفع مجزّأ قابل للاستئناف)</span>}
          </div>}
        </div>
        <button onClick={doUpload} disabled={!file}
                className="w-full mt-4 bg-[#7f1d1d] text-white py-3 rounded-xl font-bold disabled:opacity-40 hover:bg-[#991b1b]">
          رفع ومعالجة الآن
        </button>
        {progress>0 && <div className="mt-3 w-full bg-slate-100 rounded-full h-3">
          <div className="bg-[#7f1d1d] h-3 rounded-full transition-all" style={{width:progress+'%'}}></div>
        </div>}
      </div>

      {/* تسجيل مباشر */}
      <div className="bg-white rounded-xl p-6 shadow border">
        <h3 className="font-bold mb-3">2) تسجيل مباشر من الميكروفون</h3>
        <div className="flex gap-3 items-center">
          {!recording
            ? <button onClick={startRecord} className="bg-red-600 text-white px-6 py-3 rounded-xl font-bold">🎙️ بدء التسجيل</button>
            : <button onClick={stopRecord} className="bg-slate-900 text-white px-6 py-3 rounded-xl font-bold animate-pulse">⏹️ إيقاف ({fmt(elapsed)})</button>}
          <span className="text-sm text-slate-600">
            {recording ? 'جاري التسجيل — بلا حد للمدة' : 'اضغط للبدء؛ يمكنك التسجيل لمحاضرة كاملة'}
          </span>
        </div>
      </div>

      {/* يوتيوب */}
      <div className="bg-white rounded-xl p-6 shadow border">
        <h3 className="font-bold mb-3">3) رابط YouTube</h3>
        <div className="flex gap-2">
          <input value={youtube} onChange={e=>setYoutube(e.target.value)}
                 placeholder="https://www.youtube.com/watch?v=..."
                 className="flex-1 border rounded-lg px-3 py-2 ltr"/>
          <button onClick={doYoutube} className="bg-slate-900 text-white px-6 py-2 rounded-lg font-bold">تحميل ومعالجة</button>
        </div>
      </div>

      {msg && <div className="bg-green-50 border border-green-200 text-green-800 rounded-xl p-3 text-sm">{msg}</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-3 text-sm">❌ {error}</div>}

      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm">
        <b>المعالجة:</b> تفريغ كامل ← فقرات ومواضيع ← ملخصات ← قاموس مصطلحات ← أسئلة ← مصادر لكل موضوع.
        الملفات الكبيرة تُرفع على قطع وتُستأنف تلقائياً عند انقطاع الشبكة.
      </div>
    </div>
  )
}
