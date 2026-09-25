import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2, CircleAlert, Download, FileImage, Film, ImagePlus, Loader2,
  Play, RefreshCcw, Save, Scissors, ShieldCheck, Sparkles, Trash2, UploadCloud,
} from 'lucide-react'
import { fetchAPI } from '../api/client'

type FlowState = { extension_connected: boolean; project_id: string | null; ready: boolean }
type ComicStatus = { status: string; flow: FlowState; local_test_state: string }
type Dialogue = {
  id: string; panel_id: string; display_order: number; speaker_id: string; text: string
  verified: number; confidence: number | null
}
type Panel = {
  id: string; display_order: number; x: number; y: number; w: number; h: number
  crop_path: string | null; clean_path: string | null; portrait_path: string | null
  portrait_sha256: string | null; approved_sha256: string | null
  status: string; mask: Array<{x:number;y:number;w:number;h:number}>; dialogues: Dialogue[]
}
type Shot = {
  id: string; display_order: number; panel_id: string; speaker_id: string | null
  dialogue_text: string; duration_s: number; model_family: string; prompt: string
  status: string; video_path: string | null; review_status: string; review_notes: string | null
}
type Project = {
  id: string; name: string; status: string; source_width: number; source_height: number
  source_sha256: string; source_mime: string
}
type Details = { project: Project; panels: Panel[]; shots: Shot[] }
type Step = 'import' | 'analyze' | 'images' | 'approve' | 'storyboard' | 'video'

const MAX_IMAGE_BYTES = 30 * 1024 * 1024
const IMAGE_MIME = new Set(['image/png', 'image/jpeg', 'image/webp'])
const steps: Array<[Step, string]> = [
  ['import', '1. Ảnh nguồn'],
  ['analyze', '2. Khung & thoại'],
  ['images', '3. Xóa chữ / 9:16'],
  ['approve', '4. Duyệt ảnh'],
  ['storyboard', '5. Shot & prompt'],
  ['video', '6. Google Flow / video'],
]

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(path, { ...init, headers })
  if (!res.ok) {
    const body = await res.text().catch(() => res.statusText)
    throw new Error(body || `HTTP ${res.status}`)
  }
  return res.json()
}

function parseMask(text: string) {
  if (!text.trim()) return []
  const value = JSON.parse(text)
  if (!Array.isArray(value)) throw new Error('Mask phải là mảng JSON.')
  return value.map((r) => ({
    x: Number(r.x), y: Number(r.y), w: Number(r.w), h: Number(r.h),
  }))
}

function PanelEditor({
  panel, projectId, reload, setNotice,
}: {
  panel: Panel; projectId: string; reload: () => Promise<void>; setNotice: (x: string) => void
}) {
  const [maskText, setMaskText] = useState(JSON.stringify(panel.mask ?? [], null, 2))
  const [speaker, setSpeaker] = useState(panel.dialogues[0]?.speaker_id ?? 'CHAR_1')
  const [dialogue, setDialogue] = useState(panel.dialogues[0]?.text ?? '')
  const [working, setWorking] = useState(false)
  const base = `/api/comicreels/panels/${panel.id}/asset`
  const imageUrl = panel.portrait_path ? `${base}/portrait?d=${panel.portrait_sha256 ?? ''}`
    : panel.clean_path ? `${base}/clean` : `${base}/crop`

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setWorking(true)
    try { await fn(); setNotice(ok); await reload() }
    catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const saveDialogue = () => run(async () => {
    await apiJson(`/api/comicreels/panels/${panel.id}/dialogue`, {
      method: 'PUT',
      body: JSON.stringify({
        id: panel.dialogues[0]?.id ?? null,
        display_order: 0,
        speaker_id: speaker.trim() || 'UNKNOWN',
        text: dialogue,
        verified: true,
      }),
    })
  }, 'Đã lưu nguyên văn thoại và speaker. Storyboard cũ (nếu có) đã bị hủy.')

  return (
    <article className="rounded-xl border p-4" style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold">Khung {panel.display_order + 1}</div>
          <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
            {panel.w}×{panel.h} · {panel.status}
          </div>
        </div>
        {panel.approved_sha256 && panel.approved_sha256 === panel.portrait_sha256
          ? <span className="flex items-center gap-1 text-xs text-green-400"><ShieldCheck size={14}/>Đã OK</span>
          : <span className="text-xs text-amber-400">Chưa duyệt</span>}
      </div>

      <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
        <img src={imageUrl} alt={`Khung ${panel.display_order + 1}`} className="mx-auto max-h-96 max-w-full rounded object-contain" />
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-xs">
          Speaker ID
          <input value={speaker} onChange={e => setSpeaker(e.target.value)}
            className="mt-1 w-full rounded border px-3 py-2" style={{ background: 'var(--card)', borderColor: 'var(--border)' }} />
        </label>
        <label className="text-xs md:col-span-2">
          Lời thoại nguyên văn
          <textarea value={dialogue} onChange={e => setDialogue(e.target.value)} rows={3}
            placeholder="Để trống nếu khung không có thoại."
            className="mt-1 w-full rounded border px-3 py-2" style={{ background: 'var(--card)', borderColor: 'var(--border)' }} />
        </label>
        <div className="md:col-span-2 flex flex-wrap gap-2">
          <button disabled={working} onClick={saveDialogue} className="rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--border)' }}>
            <Save size={14} className="mr-1 inline"/>Lưu thoại
          </button>
        </div>

        <label className="text-xs md:col-span-2">
          Mask chữ / bong bóng (JSON tọa độ trong crop)
          <textarea value={maskText} onChange={e => setMaskText(e.target.value)} rows={4}
            placeholder={'[{"x":20,"y":15,"w":180,"h":90}]'}
            className="mt-1 w-full rounded border px-3 py-2 font-mono text-[11px]"
            style={{ background: 'var(--card)', borderColor: 'var(--border)' }} />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button disabled={working} onClick={() => run(async () => {
          await apiJson(`/api/comicreels/panels/${panel.id}/clean`, {
            method: 'POST', body: JSON.stringify({ rects: parseMask(maskText) }),
          })
        }, 'Đã tạo ảnh sạch bằng compositor local, chỉ thay pixel nằm trong mask.')}
          className="rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--border)' }}>
          <Scissors size={14} className="mr-1 inline"/>Xóa vùng mask
        </button>

        <button disabled={working} onClick={() => run(async () => {
          await apiJson(`/api/comicreels/panels/${panel.id}/portrait`, { method: 'POST' })
        }, 'Đã đặt ảnh lên canvas 9:16 mà không resize vùng tranh gốc.')}
          className="rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--border)' }}>
          <FileImage size={14} className="mr-1 inline"/>Tạo 9:16
        </button>

        <button disabled={working || !panel.portrait_path} onClick={() => run(async () => {
          await apiJson(`/api/comicreels/panels/${panel.id}/approve`, { method: 'POST' })
        }, 'Đã OK đúng hash ảnh hiện tại.')}
          className="rounded px-3 py-2 text-xs font-semibold disabled:opacity-40"
          style={{ background: 'var(--accent)', color: 'white' }}>
          <CheckCircle2 size={14} className="mr-1 inline"/>OK ảnh này
        </button>
      </div>
    </article>
  )
}

export default function ComicStudioPage() {
  const [status, setStatus] = useState<ComicStatus | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [details, setDetails] = useState<Details | null>(null)
  const [step, setStep] = useState<Step>('import')
  const [notice, setNotice] = useState('')
  const [working, setWorking] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [paidConsent, setPaidConsent] = useState(false)
  const [flowProjectId, setFlowProjectId] = useState('')
  const [visionConsent, setVisionConsent] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const refreshStatus = useCallback(async () => {
    try { setStatus(await apiJson<ComicStatus>('/api/comicreels/status')) }
    catch { setStatus(null) }
  }, [])

  const refreshProjects = useCallback(async () => {
    try { setProjects(await apiJson<Project[]>('/api/comicreels/projects')) }
    catch { setProjects([]) }
  }, [])

  const reload = useCallback(async () => {
    if (!details?.project.id) return
    setDetails(await apiJson<Details>(`/api/comicreels/projects/${details.project.id}`))
  }, [details?.project.id])

  useEffect(() => { void refreshStatus(); void refreshProjects() }, [refreshStatus, refreshProjects])
  useEffect(() => {
    const id = window.setInterval(() => { void refreshStatus() }, 15000)
    return () => window.clearInterval(id)
  }, [refreshStatus])

  useEffect(() => {
    if (!pendingFile) { setPreviewUrl(null); return }
    const url = URL.createObjectURL(pendingFile)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [pendingFile])

  const acceptLocal = useCallback((file?: File | null) => {
    if (!file) return
    if (!IMAGE_MIME.has(file.type)) { setNotice('Chỉ nhận PNG, JPG/JPEG hoặc WebP.'); return }
    if (!file.size || file.size > MAX_IMAGE_BYTES) { setNotice('Ảnh nguồn phải từ 1 byte đến 30 MB.'); return }
    setPendingFile(file)
    setNotice('Ảnh mới chỉ nằm trong trình duyệt. Bấm “Lưu dự án” để import vào ComicReels.')
  }, [])

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const target = event.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT','TEXTAREA'].includes(target.tagName))) return
      const item = Array.from(event.clipboardData?.items ?? []).find(i => i.kind === 'file' && i.type.startsWith('image/'))
      const file = item?.getAsFile()
      if (file) { event.preventDefault(); acceptLocal(file) }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [acceptLocal])

  const importSource = async () => {
    if (!pendingFile) { setNotice('Chưa có ảnh để lưu.'); return }
    setWorking(true)
    try {
      const form = new FormData()
      form.append('file', pendingFile)
      form.append('name', pendingFile.name.replace(/\.[^.]+$/, ''))
      const imported = await apiJson<{project: Project}>('/api/comicreels/projects/import', { method: 'POST', body: form })
      const loaded = await apiJson<Details>(`/api/comicreels/projects/${imported.project.id}`)
      setDetails(loaded)
      setStep('analyze')
      setPendingFile(null)
      setNotice('Đã lưu ảnh nguồn bất biến và SHA-256 vào local ComicReels storage.')
      await refreshProjects()
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const analyze = async (mode: 'heuristic' | 'vision') => {
    if (!details) return
    if (mode === 'vision' && !visionConsent) {
      setNotice('Vision sẽ gửi ảnh nguồn tới provider AI. Hãy tick xác nhận trước.')
      return
    }
    setWorking(true)
    try {
      const next = await apiJson<Details>(`/api/comicreels/projects/${details.project.id}/analyze`, {
        method: 'POST', body: JSON.stringify({ mode }),
      })
      setDetails(next)
      setStep('images')
      setNotice(mode === 'vision'
        ? 'Đã phân tích bằng provider Vision. Hãy kiểm tra khung, nguyên văn thoại và speaker trước khi xử lý ảnh.'
        : 'Đã tách khung bằng heuristic gutter. Trang bất quy tắc cần sửa tay hoặc dùng Vision.')
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const storyboard = async () => {
    if (!details) return
    setWorking(true)
    try {
      const next = await apiJson<Details>(`/api/comicreels/projects/${details.project.id}/storyboard`, {
        method: 'POST', body: JSON.stringify({ model_family: 'omni_flash' }),
      })
      setDetails(next); setStep('storyboard'); setNotice('Storyboard đã khóa ảnh hash + transcript/speaker được duyệt.')
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const generateShot = async (shot: Shot) => {
    if (!paidConsent) { setNotice('Tạo video có thể tốn tín dụng. Tick xác nhận chi phí trước.'); return }
    setWorking(true)
    try {
      await apiJson(`/api/comicreels/shots/${shot.id}/generate`, {
        method: 'POST',
        body: JSON.stringify({
          confirm_paid: true,
          idempotency_key: `ui:${details?.project.id}:${shot.id}:${shot.duration_s}`,
          project_id: flowProjectId,
          resolution: '720p',
        }),
      })
      setNotice('Đã gửi đúng một shot. Không tự retry; dùng nút kiểm tra trạng thái.')
      await reload()
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const allApproved = useMemo(() =>
    Boolean(details?.panels.length) && (details?.panels.every(p => p.portrait_sha256 && p.approved_sha256 === p.portrait_sha256) ?? false),
    [details])

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-16" lang="vi">
      <section className="rounded-2xl border p-6" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <div className="flex flex-wrap items-start gap-5">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold uppercase tracking-[.2em]" style={{ color: 'var(--accent)' }}>ComicReels Studio</div>
            <h1 className="mt-2 text-3xl font-bold">Một ảnh truyện → ảnh 9:16 → shot video</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6" style={{ color: 'var(--muted)' }}>
              Ảnh và metadata lưu cục bộ. Vision chỉ gửi ảnh ra provider khi anh chủ động chọn. Video chỉ gọi Google Flow khi anh tick xác nhận chi phí.
            </p>
          </div>
          <div className="rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
            <div className="font-semibold">{status?.flow.ready ? '● Google Flow sẵn sàng' : '○ Google Flow chưa sẵn sàng'}</div>
            <div className="mt-1" style={{ color: 'var(--muted)' }}>
              Extension: {status?.flow.extension_connected ? 'đã nối' : 'chưa nối'} · Project: {status?.flow.project_id ?? 'chưa chọn'}
            </div>
            <button onClick={() => void refreshStatus()} className="mt-2 rounded border px-2 py-1" style={{ borderColor: 'var(--border)' }}>
              <RefreshCcw size={12} className="mr-1 inline"/>Kiểm tra lại
            </button>
          </div>
        </div>
      </section>

      <section className="flex gap-2 overflow-x-auto pb-1">
        {steps.map(([id, label]) => (
          <button key={id} onClick={() => setStep(id)}
            className="whitespace-nowrap rounded-full border px-3 py-2 text-xs"
            style={{ borderColor: step === id ? 'var(--accent)' : 'var(--border)', color: step === id ? 'var(--text)' : 'var(--muted)' }}>
            {label}
          </button>
        ))}
      </section>

      {notice && (
        <div role="status" className="flex items-start gap-2 rounded-xl border p-3 text-sm"
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
          <CircleAlert size={16} className="mt-0.5 flex-none" style={{ color: 'var(--yellow)' }}/><span>{notice}</span>
        </div>
      )}

      {step === 'import' && (
        <section className="rounded-2xl border p-5" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-lg font-semibold">Ảnh truyện nguồn</h2><p className="text-xs" style={{ color:'var(--muted)' }}>Ctrl+V, kéo thả hoặc chọn file. Import mới lưu byte gốc + SHA-256.</p></div>
            {projects.length > 0 && (
              <select className="rounded border px-3 py-2 text-xs" style={{background:'var(--card)',borderColor:'var(--border)'}}
                value={details?.project.id ?? ''} onChange={async e => {
                  if (!e.target.value) return
                  const d = await apiJson<Details>(`/api/comicreels/projects/${e.target.value}`)
                  setDetails(d); setStep('analyze'); setNotice('Đã mở dự án đã lưu.')
                }}>
                <option value="">Mở dự án đã lưu…</option>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
          </div>
          <input ref={inputRef} type="file" className="sr-only" accept="image/png,image/jpeg,image/webp"
            onChange={e => { acceptLocal(e.target.files?.[0]); e.target.value = '' }}/>
          <div className="flex min-h-72 flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-6 text-center"
            style={{borderColor:dragging?'var(--accent)':'var(--border)',background:'var(--card)'}}
            onDragOver={e=>e.preventDefault()} onDragEnter={e=>{e.preventDefault();setDragging(true)}}
            onDragLeave={e=>{e.preventDefault();setDragging(false)}} onDrop={e=>{e.preventDefault();setDragging(false);acceptLocal(e.dataTransfer.files[0])}}>
            {previewUrl ? <img src={previewUrl} className="max-h-96 max-w-full rounded-lg object-contain" alt="Ảnh truyện chưa import"/>
              : <ImagePlus size={48} style={{color:'var(--accent)'}}/>}
            <div><strong>{pendingFile?.name ?? 'Dán hoặc thả ảnh truyện vào đây'}</strong>
              <div className="mt-1 text-xs" style={{color:'var(--muted)'}}>{pendingFile ? `${(pendingFile.size/1048576).toFixed(2)} MB · chưa lưu` : 'PNG/JPEG/WebP, tối đa 30 MB'}</div>
            </div>
            <div className="flex gap-2">
              <button onClick={()=>inputRef.current?.click()} className="rounded border px-4 py-2 text-sm" style={{borderColor:'var(--border)'}}><UploadCloud size={16} className="mr-1 inline"/>Chọn ảnh</button>
              <button disabled={!pendingFile||working} onClick={()=>void importSource()} className="rounded px-4 py-2 text-sm font-semibold disabled:opacity-40" style={{background:'var(--accent)',color:'white'}}>
                {working?<Loader2 size={16} className="mr-1 inline animate-spin"/>:<Save size={16} className="mr-1 inline"/>}Lưu dự án
              </button>
              {pendingFile && <button onClick={()=>setPendingFile(null)} className="rounded border px-3 py-2 text-sm" style={{borderColor:'var(--border)'}}><Trash2 size={15}/></button>}
            </div>
          </div>
        </section>
      )}

      {step === 'analyze' && details && (
        <section className="rounded-2xl border p-5" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
          <h2 className="text-lg font-semibold">Tách khung và lấy lời thoại</h2>
          <p className="mt-1 text-xs" style={{color:'var(--muted)'}}>Heuristic chỉ đọc gutter trên máy. Vision phù hợp bố cục khó nhưng gửi ảnh nguồn tới provider được cấu hình.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button disabled={working} onClick={()=>void analyze('heuristic')} className="rounded border px-4 py-2 text-sm" style={{borderColor:'var(--border)'}}><Scissors size={15} className="mr-1 inline"/>Tách khung local</button>
            <button disabled={working||!visionConsent} onClick={()=>void analyze('vision')} className="rounded border px-4 py-2 text-sm disabled:opacity-40" style={{borderColor:'var(--border)'}}><Sparkles size={15} className="mr-1 inline"/>Phân tích Vision</button>
          </div>
          <label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={visionConsent} onChange={e=>setVisionConsent(e.target.checked)}/>
            <span>Tôi hiểu chế độ Vision gửi ảnh nguồn tới provider AI đã cấu hình; sẽ kiểm tra lại bbox, thoại và speaker.</span>
          </label>
          {details.panels.length>0 && <div className="mt-4 text-sm">Đang có <strong>{details.panels.length}</strong> khung. <button className="underline" onClick={()=>setStep('images')}>Mở gallery xử lý</button></div>}
        </section>
      )}

      {(step === 'images' || step === 'approve') && details && (
        <section className="space-y-4">
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <h2 className="font-semibold">Gallery {details.panels.length} khung</h2>
            <p className="mt-1 text-xs" style={{color:'var(--muted)'}}>Kiểm tra lời thoại trước, khai báo mask vùng chữ, tạo 9:16 rồi OK từng ảnh. Ảnh sửa lại sẽ tự mất OK.</p>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {details.panels.map(p => <PanelEditor key={p.id} panel={p} projectId={details.project.id} reload={reload} setNotice={setNotice}/>)}
          </div>
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><strong>{allApproved ? 'Tất cả ảnh đã OK đúng version.' : 'Còn ảnh chưa OK.'}</strong><div className="text-xs" style={{color:'var(--muted)'}}>Backend sẽ chặn storyboard nếu hash không khớp.</div></div>
              <button disabled={!allApproved} onClick={()=>setStep('storyboard')} className="rounded px-4 py-2 text-sm disabled:opacity-40" style={{background:'var(--accent)',color:'white'}}>Sang shot & prompt</button>
            </div>
          </div>
        </section>
      )}

      {step === 'storyboard' && details && (
        <section className="space-y-4">
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><h2 className="font-semibold">Shot plan và prompt</h2><p className="text-xs" style={{color:'var(--muted)'}}>Shot giữ đoạn thoại substring nguyên văn; model mặc định Omni Flash 4/6/8/10 giây.</p></div>
              <div className="flex gap-2">
                <button onClick={()=>void storyboard()} disabled={working||!allApproved} className="rounded px-3 py-2 text-sm disabled:opacity-40" style={{background:'var(--accent)',color:'white'}}><Film size={15} className="mr-1 inline"/>Tạo storyboard</button>
                <a href={`/api/comicreels/projects/${details.project.id}/backup`} className="rounded border px-3 py-2 text-sm" style={{borderColor:'var(--border)'}}><Download size={15} className="mr-1 inline"/>Backup</a>
              </div>
            </div>
          </div>
          {details.shots.map(s=>(
            <article key={s.id} className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
              <div className="flex gap-3 text-xs"><strong>Shot {s.display_order+1}</strong><span>{s.duration_s}s</span><span>{s.speaker_id??'im lặng'}</span><span className="ml-auto">{s.status}</span></div>
              {s.dialogue_text && <blockquote className="mt-2 rounded border-l-2 pl-3 text-sm" style={{borderColor:'var(--accent)'}}>{s.dialogue_text}</blockquote>}
              <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded p-3 text-[11px]" style={{background:'var(--card)',color:'var(--muted)'}}>{s.prompt}</pre>
              <button className="mt-2 rounded border px-3 py-1.5 text-xs" style={{borderColor:'var(--border)'}} onClick={()=>void navigator.clipboard.writeText(s.prompt)}>Copy prompt</button>
            </article>
          ))}
          {details.shots.length>0 && <button onClick={()=>setStep('video')} className="rounded px-4 py-2 text-sm" style={{background:'var(--accent)',color:'white'}}>Sang Google Flow / video</button>}
        </section>
      )}

      {step === 'video' && details && (
        <section className="space-y-4">
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <h2 className="font-semibold">Google Flow và video</h2>
            <p className="mt-1 text-xs" style={{color:'var(--muted)'}}>Không tự gửi batch. Anh có thể copy prompt/ảnh thủ công; nút dưới chỉ gửi đúng shot khi đã tick xác nhận chi phí.</p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="text-xs">Flow Project UUID (để trống dùng config/session)
                <input value={flowProjectId} onChange={e=>setFlowProjectId(e.target.value)} className="mt-1 w-full rounded border px-3 py-2" style={{background:'var(--card)',borderColor:'var(--border)'}}/>
              </label>
              <label className="flex items-center gap-2 self-end rounded border p-3 text-xs" style={{borderColor:'var(--border)'}}>
                <input type="checkbox" checked={paidConsent} onChange={e=>setPaidConsent(e.target.checked)}/>
                Tôi hiểu thao tác Tạo video có thể tiêu tốn tín dụng Google Flow.
              </label>
            </div>
          </div>
          {details.shots.map(s=>(
            <article key={s.id} className="flex flex-wrap items-center gap-3 rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
              <div className="min-w-0 flex-1"><strong className="text-sm">Shot {s.display_order+1}</strong><div className="truncate text-xs" style={{color:'var(--muted)'}}>{s.dialogue_text||'Cảnh phản ứng im lặng'} · {s.duration_s}s · {s.status}</div></div>
              <button disabled={working||!paidConsent} onClick={()=>void generateShot(s)} className="rounded border px-3 py-2 text-xs disabled:opacity-40" style={{borderColor:'var(--border)'}}><Play size={14} className="mr-1 inline"/>Tạo đúng shot này</button>
              <button disabled={working||s.status!=='PROCESSING'} onClick={async()=>{
                try{await apiJson(`/api/comicreels/shots/${s.id}/poll`,{method:'POST'});setNotice('Đã kiểm tra trạng thái, nếu có signed URL video đã được lưu local.');await reload()}catch(e){setNotice(e instanceof Error?e.message:String(e))}
              }} className="rounded border px-3 py-2 text-xs disabled:opacity-40" style={{borderColor:'var(--border)'}}>Kiểm tra trạng thái</button>
            </article>
          ))}
          <div className="rounded-xl border p-4 text-xs" style={{background:'var(--surface)',borderColor:'var(--border)',color:'var(--muted)'}}>
            Review/ghép chỉ hoạt động sau khi từng shot có file video và được APPROVED. API hỗ trợ đăng ký file video, review từng shot và ghép ffmpeg; local test sẽ kiểm tra luồng này sau.
          </div>
        </section>
      )}
    </div>
  )
}
