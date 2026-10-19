import { useEffect, useState } from 'react'
import api from '../api/client'

/** شكل مصدر واحد كما يعيده الـ API الحقيقي */
type Resource = {
  id: number
  provider: string
  title: string
  url: string
  snippet?: string
  thumbnail?: string | null
  duration_seconds?: number | null
  channel?: string | null
  lang?: string
}

type Topic = {
  id: number
  order: number
  title: string
  excerpt: string
  key_terms: string[]
  start_seconds: number
  end_seconds: number
  resources: Resource[]
}

const PROVIDER_META: Record<string, { label: string; icon: string; color: string; border: string }> = {
  youtube:     { label: 'يوتيوب',      icon: '▶', color: 'bg-red-600',     border: 'border-red-200' },
  wikipedia:   { label: 'ويكيبيديا',   icon: 'W', color: 'bg-slate-700',   border: 'border-slate-200' },
  wikiversity: { label: 'ويكي الجامعة', icon: 'V', color: 'bg-emerald-700', border: 'border-emerald-200' },
  wikibooks:   { label: 'ويكي الكتب',  icon: 'B', color: 'bg-amber-700',   border: 'border-amber-200' },
  arxiv:       { label: 'arXiv',       icon: 'a', color: 'bg-rose-800',    border: 'border-rose-200' },
}

const fmtDuration = (sec?: number | null) => {
  if (!sec) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

/** استخراج معرّف فيديو يوتيوب من الرابط لتضمينه داخل الصفحة */
const youtubeId = (url: string): string | null => {
  const m = url.match(/(?:v=|youtu\.be\/|embed\/)([A-Za-z0-9_-]{11})/)
  return m ? m[1] : null
}

/**
 * بطاقة مصدر واحدة. تعرض المصغّرة إن توفّرت، وتتحول إلى مشغل مضمّن
 * عند الضغط على «شاهد هنا» (يوتيوب فقط)، مع رابط خارجي دائماً.
 */
function SourceCard({ r }: { r: Resource }) {
  const [playing, setPlaying] = useState(false)
  const [imgFailed, setImgFailed] = useState(false)
  const meta = PROVIDER_META[r.provider] || { label: r.provider, icon: '🔗', color: 'bg-slate-600', border: 'border-slate-200' }
  const ytId = r.provider === 'youtube' ? youtubeId(r.url) : null

  // مصادر بلا صورة (ويكيبيديا/ويكي الجامعة/arXiv): بطاقة نصية مضغوطة بدل مربع فارغ
  const compact = !r.thumbnail && r.provider !== 'youtube'
  if (compact) {
    return (
      <div className={`border ${meta.border} rounded-xl p-3 bg-white hover:shadow-md transition-shadow flex gap-3`}>
        <div className={`w-9 h-9 rounded-lg ${meta.color} text-white font-black flex items-center justify-center shrink-0`}>
          {meta.icon}
        </div>
        <div className="min-w-0">
          <div className="text-[10px] text-slate-500 font-bold">{meta.label}</div>
          <a href={r.url} target="_blank" rel="noopener noreferrer"
             className="text-sm font-bold leading-6 line-clamp-2 hover:text-[#7f1d1d] block">
            {r.title}
          </a>
          {r.snippet && <div className="text-xs text-slate-600 mt-1 line-clamp-2 leading-5">{r.snippet}</div>}
          <a href={r.url} target="_blank" rel="noopener noreferrer"
             className="text-xs font-bold text-[#7f1d1d] hover:underline inline-block mt-1">
            فتح المصدر ↗
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className={`border ${meta.border} rounded-xl overflow-hidden bg-white hover:shadow-md transition-shadow`}>
      {playing && ytId ? (
        <div className="relative w-full" style={{ aspectRatio: '16 / 9' }}>
          <iframe
            className="absolute inset-0 w-full h-full"
            src={`https://www.youtube.com/embed/${ytId}?autoplay=1&rel=0`}
            title={r.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      ) : (
        <a href={r.url} target="_blank" rel="noopener noreferrer" className="block relative group">
          {r.thumbnail && !imgFailed ? (
            <img
              src={r.thumbnail}
              alt={r.title}
              loading="lazy"
              onError={() => setImgFailed(true)}
              className="w-full object-cover bg-slate-100"
              style={{ aspectRatio: '16 / 9' }}
            />
          ) : (
            /* بديل محلي عند تعذّر تحميل الصورة (شبكة محجوبة/بلا اتصال) */
            <div className={`w-full flex items-center justify-center ${meta.color}`} style={{ aspectRatio: '16 / 9' }}>
              <span className="text-white text-3xl font-black opacity-90">{meta.icon}</span>
            </div>
          )}
          <span className={`absolute top-2 right-2 text-[11px] text-white px-2 py-0.5 rounded-full font-bold ${meta.color}`}>
            {meta.label}
          </span>
          {r.duration_seconds ? (
            <span className="absolute bottom-2 left-2 text-[11px] bg-black/80 text-white px-1.5 py-0.5 rounded ltr">
              {fmtDuration(r.duration_seconds)}
            </span>
          ) : null}
        </a>
      )}

      <div className="p-3">
        <a href={r.url} target="_blank" rel="noopener noreferrer"
           className="text-sm font-bold leading-6 line-clamp-2 hover:text-[#7f1d1d] block">
          {r.title}
        </a>
        {r.channel && <div className="text-[11px] text-slate-500 mt-1 truncate">{r.channel}</div>}
        {r.snippet && <div className="text-xs text-slate-600 mt-1 line-clamp-2 leading-5">{r.snippet}</div>}
        <div className="flex gap-2 mt-2">
          <a href={r.url} target="_blank" rel="noopener noreferrer"
             className="text-xs font-bold text-[#7f1d1d] hover:underline">
            فتح المصدر ↗
          </a>
          {ytId && !playing && (
            <button onClick={() => setPlaying(true)} className="text-xs font-bold text-slate-600 hover:underline">
              شاهد هنا
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** بحث يدوي حر: يظهر بنفس شكل البطاقات، ويقول بصراحة إن لم يجد */
function FreeSearch() {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Resource[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const run = async (term?: string) => {
    const query = (term ?? q).trim()
    if (query.length < 2) return
    setQ(query)
    setBusy(true); setMsg('')
    try {
      const res = await api.get('/api/v1/lectures/resources/search', { params: { q: query, limit: 8 } })
      setItems(res.data.items || [])
      if (!res.data.items?.length) setMsg('لا توجد نتائج مطابقة لهذا البحث.')
    } catch (e: any) {
      setItems([]); setMsg(e.response?.data?.detail || 'تعذّر البحث الآن — تحقق من اتصال الخادم بالإنترنت.')
    }
    setBusy(false)
  }

  return (
    <div className="border rounded-xl p-4 bg-slate-50">
      <div className="font-bold text-sm mb-1">ابحث عن شرح لأي مفهوم بنفسك</div>
      <p className="text-xs text-slate-500 mb-3">نفس المصادر الحقيقية (يوتيوب/ويكيبيديا...) — مفيد إن أردت التوسّع في نقطة لم تظهر كموضوع.</p>
      <form
        onSubmit={(e) => { e.preventDefault(); run() }}
        className="flex gap-2"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="مثال: القانون الثالث لنيوتن"
          className="flex-1 border rounded-lg px-3 py-2 text-sm bg-white"
        />
        <button disabled={busy || q.trim().length < 2}
                className="bg-[#7f1d1d] disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-bold">
          {busy ? 'يبحث...' : 'ابحث'}
        </button>
      </form>
      {msg && <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2 mt-3">{msg}</div>}
      {items && items.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mt-3">
          {items.map((r) => <SourceCard key={r.url} r={{ ...r, id: 0 }} />)}
        </div>
      )}
    </div>
  )
}

/**
 * تبويب «الشرح والمصادر»: لكل موضوع مستخرج من المحاضرة،
 * مقتطف من كلام المحاضرة + روابط شرح خارجية حقيقية داخل مسار الشرح.
 */
export default function TopicSources({
  topics, lectureId, isMedia, onSeek, onChanged,
}: {
  topics: Topic[]
  lectureId: string | undefined
  isMedia: boolean
  onSeek?: (sec: number) => void
  onChanged?: () => void
}) {
  const [relinking, setRelinking] = useState(false)
  const [note, setNote] = useState('')
  const [openExcerpt, setOpenExcerpt] = useState<Record<number, boolean>>({})

  useEffect(() => { setNote('') }, [topics])

  const relink = async () => {
    if (!lectureId) return
    setRelinking(true); setNote('')
    try {
      const res = await api.post(`/api/v1/lectures/${lectureId}/topics/relink`)
      setNote(`تم تحديث المصادر: ${res.data.resources} مصدراً لـ ${res.data.topics} مواضيع.`)
      onChanged?.()
    } catch (e: any) {
      setNote(e.response?.data?.detail || 'تعذّر تحديث المصادر الآن.')
    }
    setRelinking(false)
  }

  if (!topics || topics.length === 0) {
    return (
      <div className="space-y-4">
        <div className="border rounded-xl p-8 text-center bg-slate-50">
          <div className="text-4xl mb-3">🧭</div>
          <p className="font-bold">لم تُستخرج مواضيع من هذه المحاضرة لهذا الحد بعد</p>
          <p className="text-sm text-slate-500 mt-1">أعد المعالجة من زر «إعادة المعالجة» — سيُقسَّم النص إلى مواضيع ويُبحث لكل موضوع عن شرح خارجي.</p>
        </div>
        <FreeSearch />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">
          {topics.length} مواضيع مستخرجة من محاضرتك — لكل موضوع شرح خارجي مرتبط به.
        </p>
        <button onClick={relink} disabled={relinking}
                className="border px-3 py-1.5 rounded-lg text-xs font-bold hover:bg-slate-50 disabled:opacity-50">
          {relinking ? 'جاري البحث...' : '↻ تحديث المصادر'}
        </button>
      </div>
      {note && <div className="text-xs bg-emerald-50 border border-emerald-200 text-emerald-800 rounded p-2">{note}</div>}

      {topics.map((t) => (
        <section key={t.id} className="border rounded-xl overflow-hidden bg-white">
          <header className="bg-orange-50/60 border-b px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-7 h-7 rounded-full bg-[#7f1d1d] text-white text-xs font-black flex items-center justify-center shrink-0">
                {t.order + 1}
              </span>
              <h3 className="font-bold text-lg">{t.title}</h3>
              {isMedia && t.end_seconds > 0 && (
                <button onClick={() => onSeek?.(t.start_seconds)}
                        className="text-[11px] border rounded-full px-2 py-0.5 text-[#7f1d1d] font-bold ltr hover:bg-white">
                  [{Math.floor(t.start_seconds / 60)}:{String(t.start_seconds % 60).padStart(2, '0')}]
                </button>
              )}
              <span className="text-[11px] text-slate-500 mr-auto">{t.resources.length} مصدر</span>
            </div>

            {t.key_terms?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {t.key_terms.slice(0, 6).map((k) => (
                  <span key={k} className="text-[11px] bg-white border rounded-full px-2 py-0.5 text-slate-600">{k}</span>
                ))}
              </div>
            )}
          </header>

          <div className="p-4 space-y-3">
            {t.excerpt && (
              <div className="text-sm leading-7 text-slate-700 bg-slate-50 border-r-4 border-[#7f1d1d]/30 rounded px-3 py-2">
                <span className={openExcerpt[t.id] ? '' : 'line-clamp-2'}>{t.excerpt}</span>
                {t.excerpt.length > 160 && (
                  <button onClick={() => setOpenExcerpt((s) => ({ ...s, [t.id]: !s[t.id] }))}
                          className="text-xs text-[#7f1d1d] font-bold mt-1 block">
                    {openExcerpt[t.id] ? 'إخفاء' : 'اقرأ المقطع كاملاً'}
                  </button>
                )}
              </div>
            )}

            {t.resources.length === 0 ? (
              <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded p-3">
                لم نجد مصدراً مطابقاً لهذا الموضوع تحديداً. استخدم البحث اليدوي بالأسفل — لن نعرض لك روابط غير ذات صلة.
              </div>
            ) : (
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {t.resources.map((r) => <SourceCard key={r.id || r.url} r={r} />)}
              </div>
            )}
          </div>
        </section>
      ))}

      <FreeSearch />
    </div>
  )
}
