import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import Layout from './components/Layout'
import Home from './pages/Home'
import Upload from './pages/Upload'
import Lecture from './pages/Lecture'

// تسجيل Service Worker لدعم PWA (يعمل بلا إنترنت للهيكل)
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Home/>} />
          <Route path="/upload" element={<Upload/>} />
          <Route path="/lecture/:id" element={<Lecture/>} />
        </Routes>
      </Layout>
    </BrowserRouter>
  </React.StrictMode>,
)
