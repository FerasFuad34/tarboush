import axios from 'axios'

const api = axios.create({
  // رابط نسبي: Vite يمرّر /api إلى الباك-إند في التطوير، وnginx في الإنتاج
  // هذا يمنع أي اتصال بـ localhost من متصفح المستخدم
  baseURL: import.meta.env.VITE_API_URL || '',
  timeout: 120000
})

// إضافة trace id
api.interceptors.request.use(cfg => {
  cfg.headers['X-Request-ID'] = Math.random().toString(36).slice(2,9)
  return cfg
})

export default api
export const uploadLecture = (file: File, title?: string) => {
  const fd = new FormData()
  fd.append('file', file)
  if(title) fd.append('title', title)
  return api.post('/api/v1/lectures/upload', fd, { headers: {'Content-Type': 'multipart/form-data'}})
}
export const listLectures = () => api.get('/api/v1/lectures')
export const getLecture = (id:number) => api.get(`/api/v1/lectures/${id}`)
export const getProgress = (id:number) => api.get(`/api/v1/lectures/${id}/progress`)
export const retryLecture = (id:number) => api.post(`/api/v1/lectures/${id}/retry`)
export const deleteLecture = (id:number) => api.delete(`/api/v1/lectures/${id}`)
export const getHealth = () => api.get('/health')
