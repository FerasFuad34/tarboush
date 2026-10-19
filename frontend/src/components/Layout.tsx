import { Link, useLocation } from 'react-router-dom'

export default function Layout({children}:{children: React.ReactNode}){
  const loc = useLocation()
  const nav = [
    {to:'/', label:'الرئيسية'},
    {to:'/upload', label:'رفع محاضرة'},
  ]
  return (
    <div className="min-h-screen rtl">
      <header className="bg-[#7f1d1d] text-white shadow-lg sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            {/* شعار طربوش: دائرة + شرابة + كتاب، SVG مضمّن يعمل بلا خطوط أو صور خارجية */}
            <svg width="40" height="40" viewBox="0 0 48 48" aria-label="شعار طربوش" role="img">
              <circle cx="24" cy="24" r="23" fill="#fffaf0" />
              <path d="M12 26 L24 19 L36 26 L24 33 Z" fill="#b91c1c" />
              <path d="M24 33 L24 39" stroke="#b91c1c" strokeWidth="2.5" strokeLinecap="round" />
              <circle cx="24" cy="40.5" r="2.6" fill="#f59e0b" />
              <path d="M18 29.5 L18 34.5" stroke="#7f1d1d" strokeWidth="1.6" opacity=".6" />
              <path d="M30 29.5 L30 34.5" stroke="#7f1d1d" strokeWidth="1.6" opacity=".6" />
            </svg>
            <div>
              <div className="font-bold text-xl leading-none">طربوش</div>
              <div className="text-xs opacity-80">ذاكر محاضرتك بذكاء</div>
            </div>
          </Link>
          <nav className="flex gap-4">
            {nav.map(n=>(
              <Link key={n.to} to={n.to} className={`px-4 py-2 rounded-lg text-sm ${loc.pathname===n.to?'bg-white text-[#7f1d1d] font-bold':'hover:bg-white/20'}`}>{n.label}</Link>
            ))}
          </nav>
        </div>
      </header>
      <main className="max-w-6xl mx-auto px-4 py-6">{children}</main>
      <footer className="text-center text-xs text-slate-500 py-8">صنع للطلاب في اليمن والعالم العربي • طربوش M1 • يعمل محلياً بلا تكلفة</footer>
    </div>
  )
}
