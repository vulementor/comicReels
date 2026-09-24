import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, CircleAlert, ImagePlus, RefreshCcw, Trash2, UploadCloud, WifiOff } from 'lucide-react'
import { fetchAPI } from '../api/client'

type Health = { status?: string; extension_connected?: boolean }
type FlowStatus = { connected?: boolean; authenticated?: boolean; flow_project_id?: string | null }
type ConnectionState = 'checking' | 'backend-offline' | 'extension-offline' | 'flow-unavailable' | 'ready'
const IMAGE_MIME = new Set(['image/png', 'image/jpeg', 'image/webp'])
const MAX_IMAGE_BYTES = 20 * 1024 * 1024

function connectionState(health: Health | null, flow: FlowStatus | null, apiOk: boolean): ConnectionState {
  if (!apiOk) return 'backend-offline'
  if (!health?.extension_connected) return 'extension-offline'
  if (!flow?.connected || !flow.authenticated || !flow.flow_project_id) return 'flow-unavailable'
  return 'ready'
}

export default function ComicStudioPage() {
  const [image, setImage] = useState<File | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [dragging, setDragging] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [flow, setFlow] = useState<FlowStatus | null>(null)
  const [apiOk, setApiOk] = useState(false)
  const [checking, setChecking] = useState(true)
  const fileInput = useRef<HTMLInputElement>(null)

  const refreshConnection = useCallback(async () => {
    setChecking(true)
    try {
      const h = await fetchAPI<Health>('/health')
      setHealth(h)
      setApiOk(h.status === 'ok')
      if (h.status !== 'ok' || !h.extension_connected) {
        setFlow(null)
      } else {
        // A healthy backend is not the same as an authenticated Flow session.
        const f = await fetchAPI<FlowStatus>('/api/flow/status')
        setFlow(f)
      }
    } catch {
      setHealth(null)
      setFlow(null)
      setApiOk(false)
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void refreshConnection()
    const interval = window.setInterval(() => { void refreshConnection() }, 15000)
    return () => window.clearInterval(interval)
  }, [refreshConnection])

  useEffect(() => {
    if (!image) { setImageUrl(null); return }
    const url = URL.createObjectURL(image)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [image])

  const acceptFile = useCallback((file?: File) => {
    if (!file) return
    if (!IMAGE_MIME.has(file.type)) {
      setMessage('Chỉ hỗ trợ ảnh PNG, JPG hoặc WebP.')
      return
    }
    if (file.size === 0 || file.size > MAX_IMAGE_BYTES) {
      setMessage('Ảnh phải có dung lượng từ 1 byte đến 20 MB.')
      return
    }
    setImage(file)
    setMessage('Ảnh chỉ được xem trước trên trình duyệt. Chưa tải lên máy chủ hoặc Google Flow.')
  }, [])

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const target = event.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA'].includes(target.tagName))) return
      const file = Array.from(event.clipboardData?.items ?? []).find(item => item.kind === 'file' && item.type.startsWith('image/'))?.getAsFile()
      if (file) { event.preventDefault(); acceptFile(file) }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [acceptFile])

  const status = checking && !health ? 'checking' : connectionState(health, flow, apiOk)
  const stateText: Record<ConnectionState, string> = {
    checking: 'Đang kiểm tra kết nối…',
    'backend-offline': 'Máy chủ FlowKit chưa hoạt động',
    'extension-offline': 'Máy chủ hoạt động, Chrome Extension chưa kết nối',
    'flow-unavailable': 'Extension đã kết nối, cần đăng nhập Flow và chọn dự án',
    ready: 'Google Flow sẵn sàng',
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 pb-12" lang="vi">
      <section className="rounded-2xl border p-6 sm:p-8" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <div className="mb-2 text-xs font-semibold uppercase tracking-widest" style={{ color: 'var(--accent)' }}>ComicReels Studio · Phân đoạn 2</div>
        <h1 className="text-3xl font-bold tracking-tight">Biến truyện tranh thành video</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6" style={{ color: 'var(--muted)' }}>Dán ảnh truyện nhiều khung để xem trước. Các bước phân tích, tách ảnh bối cảnh 9:16 và tạo video sẽ được bổ sung ở các phân đoạn sau.</p>
      </section>

      <section aria-label="Trạng thái Google Flow" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <div className="flex items-start gap-3">
          {status === 'ready' ? <CheckCircle2 aria-hidden="true" className="mt-0.5 text-green-400" /> : status === 'checking' ? <RefreshCcw aria-hidden="true" className="mt-0.5 animate-spin" /> : status === 'backend-offline' ? <WifiOff aria-hidden="true" className="mt-0.5 text-amber-400" /> : <CircleAlert aria-hidden="true" className="mt-0.5 text-amber-400" />}
          <div>
            <h2 className="font-semibold">{stateText[status]}</h2>
            <p className="mt-1 text-xs leading-5" style={{ color: 'var(--muted)' }}>{status === 'ready' ? 'Trạng thái được lấy từ máy chủ và phiên Flow hiện tại.' : 'Anh vẫn có thể dán ảnh và xem trước mà không cần kết nối Google Flow.'}</p>
          </div>
        </div>
        <button type="button" onClick={() => { void refreshConnection() }} disabled={checking} className="rounded-lg border px-3 py-2 text-xs disabled:opacity-50" style={{ borderColor: 'var(--border)' }}>Kiểm tra lại</button>
      </section>

      <section className="rounded-2xl border p-5 sm:p-7" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <h2 className="text-lg font-semibold">1. Dán ảnh truyện tranh</h2>
        <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>Nhấn Ctrl + V, chọn ảnh hoặc kéo thả tệp vào vùng bên dưới.</p>
        <input ref={fileInput} type="file" className="sr-only" aria-label="Chọn ảnh truyện tranh" accept="image/png,image/jpeg,image/webp" onChange={event => { acceptFile(event.target.files?.[0]); event.target.value = '' }} />
        <div onDragEnter={event => { event.preventDefault(); setDragging(true) }} onDragOver={event => event.preventDefault()} onDragLeave={event => { event.preventDefault(); setDragging(false) }} onDrop={event => { event.preventDefault(); setDragging(false); acceptFile(event.dataTransfer.files[0]) }} className="mt-5 flex min-h-64 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-6 text-center" style={{ borderColor: dragging ? 'var(--accent)' : 'var(--border)', background: 'var(--card)' }}>
          {imageUrl ? <img src={imageUrl} alt="Ảnh truyện tranh gốc đang xem trước" className="max-h-80 max-w-full rounded-lg object-contain" /> : <ImagePlus aria-hidden="true" size={42} style={{ color: 'var(--accent)' }} />}
          <div>
            <p className="font-semibold">{image ? image.name : 'Thả ảnh truyện tranh của anh vào đây'}</p>
            <p className="mt-1 text-xs" style={{ color: 'var(--muted)' }}>{image ? (image.size / 1024 / 1024).toFixed(2) + ' MB · Chỉ xem trước trên máy anh' : 'PNG, JPG, WebP · tối đa 20 MB · chưa tải lên máy chủ'}</p>
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            <button type="button" onClick={() => fileInput.current?.click()} className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold" style={{ background: 'var(--accent)', color: 'white' }}><UploadCloud aria-hidden="true" size={17} />{image ? 'Đổi ảnh' : 'Chọn ảnh'}</button>
            {image && <button type="button" onClick={() => { setImage(null); setMessage('Đã xóa ảnh xem trước khỏi giao diện.') }} className="inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm" style={{ borderColor: 'var(--border)' }}><Trash2 aria-hidden="true" size={16} />Bỏ ảnh</button>}
          </div>
        </div>
        {message && <p role="status" className="mt-3 text-sm" style={{ color: 'var(--muted)' }}>{message}</p>}
      </section>

      <section aria-label="Các bước tiếp theo" className="grid gap-3 md:grid-cols-3">
        {['2. Tách ảnh bối cảnh', '3. Duyệt từng ảnh', '4. Tạo prompt và video'].map(step => (
          <div key={step} className="rounded-xl border p-4 opacity-60" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
            <h3 className="font-semibold">{step}</h3><p className="mt-2 text-xs" style={{ color: 'var(--muted)' }}>Chưa khả dụng trong phân đoạn này.</p>
          </div>
        ))}
      </section>
    </div>
  )
}
