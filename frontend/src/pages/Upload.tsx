import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'

export default function Upload(){
  const [file,setFile]=useState<File|null>(null)
  const [title,setTitle]=useState('')
  const [youtube,setYoutube]=useState('')
  const [progress,setProgress]=useState(0)
  const [msg,setMsg]=useState('')
  const [error,setError]=useState('')
  const [recording,setRecording]=useState(false)
  const mediaRef = useRef<MediaRecorder|null>(null)
  const navigate = useNavigate()

  const doUpload=async()=>{
    if(!file){ setError('اختر ملفاً أولاً'); return }
    setError(''); setMsg('جاري الرفع...'); setProgress(10)
    const fd = new FormData()
    fd.append('file', file)
    if(title) fd.append('title', title)
    try{
      const res = await api.post('/api/v1/lectures/upload', fd, {
        headers:{'Content-Type':'multipart/form-data'},
        onUploadProgress:(e)=>{ if(e.total) setProgress(Math.round(e.loaded*100/e.total)) }
      })
      setMsg(res.data.deduplicated ? 'هذا الملف موجود مسبقاً - تم إرجاع الأصل ✅' : 'تم الرفع! جاري المعالجة في الخلفية...')
      setTimeout(()=> navigate(`/lecture/${res.data.id}`), 800)
    }catch(err:any){
      setError(err.response?.data?.detail || 'فشل الرفع: '+err.message)
      setProgress(0)
    }
  }

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

  const startRecord=async()=>{
    try{
      const stream = await navigator.mediaDevices.getUserMedia({audio:true})
      const mr = new MediaRecorder(stream)
      const chunks:Blob[]=[]
      mr.ondataavailable=e=> chunks.push(e.data)
      mr.onstop=()=>{
        const blob = new Blob(chunks, {type:'audio/webm'})
        const f = new File([blob], `تسجيل_${new Date().toISOString().slice(0,10)}.webm`, {type:'audio/webm'})
        setFile(f); setMsg('تم التسجيل - جاهز للرفع (اضغط رفع الآن)')
      }
      mediaRef.current=mr
      mr.start(); setRecording(true); setMsg('جاري التسجيل... اضغط إيقاف عند الانتهاء')
      setTimeout(()=>{ if(mr.state==='recording'){ mr.stop(); setRecording(false)}}, 120000) // حد 2 دقيقة للعرض
    }catch(e:any){ setError('الميكروفون غير متاح: '+e.message)}
  }
  const stopRecord=()=>{
    if(mediaRef.current && mediaRef.current.state==='recording'){
      mediaRef.current.stop(); setRecording(false)
      mediaRef.current.stream.getTracks().forEach(t=>t.stop())
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">رفع محاضرة جديدة</h1>
      <p className="text-slate-600 text-sm">يدعم: MP3/WAV/M4A/MP4/PDF/DOCX/TXT/PPTX/ZIP + تسجيل مباشر + رابط YouTube. المدة المقترحة لـ M1: 30 دقيقة. الحد الأقصى 500MB.</p>

      {/* رفع ملف */}
      <div className="bg-white rounded-xl p-6 shadow border">
        <h3 className="font-bold mb-3">1) رفع ملف من جهازك</h3>
        <input type="text" placeholder="عنوان المحاضرة (اختياري) - مثلاً: محاضرة فيزياء 1 - الفصل الأول" value={title} onChange={e=>setTitle(e.target.value)} className="w-full border rounded-lg px-3 py-2 mb-3"/>
        <div className="border-2 border-dashed rounded-xl p-6 text-center bg-orange-50/50">
          <input type="file" id="file" onChange={e=>setFile(e.target.files?.[0]||null)} accept=".mp3,.wav,.m4a,.mp4,.pdf,.docx,.txt,.md,.pptx,.zip,video/*,audio/*" className="hidden"/>
          <label htmlFor="file" className="cursor-pointer">
            <div className="text-4xl mb-2">📁</div>
            <div className="font-bold text-[#7f1d1d]">اضغط لاختيار ملف</div>
            <div className="text-xs text-slate-500 mt-1">أو اسحب الملف هنا</div>
          </label>
          {file && <div className="mt-3 text-sm bg-white border rounded p-2">المحدد: <b>{file.name}</b> - {(file.size/1024/1024).toFixed(2)} MB</div>}
        </div>
        <button onClick={doUpload} disabled={!file} className="w-full mt-4 bg-[#7f1d1d] text-white py-3 rounded-xl font-bold disabled:opacity-40 hover:bg-[#991b1b]">رفع ومعالجة الآن</button>
        {progress>0 && <div className="mt-3 w-full bg-slate-100 rounded-full h-3"><div className="bg-[#7f1d1d] h-3 rounded-full transition-all" style={{width:progress+'%'}}></div></div>}
      </div>

      {/* تسجيل مباشر */}
      <div className="bg-white rounded-xl p-6 shadow border">
        <h3 className="font-bold mb-3">2) تسجيل مباشر من الميكروفون</h3>
        <div className="flex gap-3">
          {!recording ? <button onClick={startRecord} className="bg-red-600 text-white px-6 py-3 rounded-xl font-bold">🎙️ بدء التسجيل</button>
          : <button onClick={stopRecord} className="bg-slate-900 text-white px-6 py-3 rounded-xl font-bold animate-pulse">⏹️ إيقاف التسجيل</button>}
          <span className="text-sm text-slate-600 self-center">{recording ? 'جاري التسجيل... تحدث بوضوح' : 'سيُحفظ كـ WebM ثم يحوّل تلقائياً'}</span>
        </div>
      </div>

      {/* يوتيوب */}
      <div className="bg-white rounded-xl p-6 shadow border">
        <h3 className="font-bold mb-3">3) رابط YouTube</h3>
        <div className="flex gap-2">
          <input value={youtube} onChange={e=>setYoutube(e.target.value)} placeholder="https://www.youtube.com/watch?v=..." className="flex-1 border rounded-lg px-3 py-2 ltr"/>
          <button onClick={doYoutube} className="bg-slate-900 text-white px-6 py-2 rounded-lg font-bold">تحميل ومعالجة</button>
        </div>
      </div>

      {msg && <div className="bg-green-50 border border-green-200 text-green-800 rounded-xl p-3 text-sm">{msg}</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-3 text-sm">❌ {error}</div>}

      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm">
        <b>ملاحظة:</b> إذا كان الاتصال ضعيفاً، سيُستأنف الرفع تلقائياً (في M3). حالياً إن انقطع الاتصال أعد المحاولة - النظام يمنع التكرار بالـ hash.
      </div>
    </div>
  )
}
