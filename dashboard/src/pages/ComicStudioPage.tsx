import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckCircle2, CircleAlert, Download, Film, ImagePlus, Loader2,
  Play, RefreshCcw, Save, Scissors, ShieldCheck, Sparkles, Trash2, UploadCloud,
} from 'lucide-react'

type FlowState = { extension_connected: boolean; project_id: string | null; ready: boolean }
type AIState = { provider: string; configured: boolean; vision_model: string; image_model: string }
type ComicStatus = { status: string; flow: FlowState; ai: AIState; local_test_state: string }
type Dialogue = {
  id: string; panel_id: string; display_order: number; speaker_id: string; text: string
  verified: number; confidence: number | null
}
type Panel = {
  id: string; display_order: number; x: number; y: number; w: number; h: number
  crop_path: string | null; clean_path: string | null; portrait_path: string | null
  portrait_sha256: string | null; approved_sha256: string | null; visual_anchor: string | null
  status: string; updated_at?: string; mask: Array<{x:number;y:number;w:number;h:number}>; dialogues: Dialogue[]
}
type Shot = {
  id: string; display_order: number; panel_id: string; speaker_id: string | null
  dialogue_text: string; duration_s: number; model_family: string; prompt: string
  status: string; video_path: string | null; review_status: string; review_notes: string | null
  updated_at?: string; idempotency_key?: string | null; flow_payload?: { error?: string } | null
}
type Project = {
  id: string; name: string; status: string; source_width: number; source_height: number
  source_sha256: string; source_mime: string; ai_conversation_url: string | null
}
type Details = { project: Project; panels: Panel[]; shots: Shot[]; analysis_warnings?: string[] }
type Step = 'import' | 'analyze' | 'images' | 'approve' | 'storyboard' | 'video'

const LAST_PROJECT_KEY = 'comicreels:last-project'
const REQUIRED_REFERENCES = 3

const MAX_IMAGE_BYTES = 30 * 1024 * 1024
const IMAGE_MIME = new Set(['image/png', 'image/jpeg', 'image/webp'])
const steps: Array<[Step, string]> = [
  ['import', '1. Ảnh nguồn'],
  ['analyze', '2. Khung & thoại'],
  ['images', '3. Xóa chữ / 9:16'],
  ['approve', '4. Duyệt ảnh'],
  ['storyboard', '5. Kịch bản thành phần'],
  ['video', '6. 3 ảnh + kịch bản → Flow'],
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
  panel, reload, setNotice, aiConfigured,
}: {
  panel: Panel; reload: () => Promise<void>; setNotice: (x: string) => void; aiConfigured: boolean
}) {
  const [maskText, setMaskText] = useState(JSON.stringify(panel.mask ?? [], null, 2))
  const [bbox, setBbox] = useState({ x: panel.x, y: panel.y, w: panel.w, h: panel.h })
  const [dialogues, setDialogues] = useState(() =>
    panel.dialogues.length ? panel.dialogues.map(d => ({ ...d })) :
      [{ id: '', panel_id: panel.id, display_order: 0, speaker_id: 'CHAR_1', text: '', verified: 0, confidence: null }]
  )
  const [working, setWorking] = useState(false)

  const maskSignature = JSON.stringify(panel.mask ?? [])

  useEffect(() => {
    setBbox({ x: panel.x, y: panel.y, w: panel.w, h: panel.h })
  }, [panel.id, panel.x, panel.y, panel.w, panel.h])

  useEffect(() => {
    setDialogues(panel.dialogues.length ? panel.dialogues.map(d => ({ ...d })) :
      [{ id: '', panel_id: panel.id, display_order: 0, speaker_id: 'CHAR_1', text: '', verified: 0, confidence: null }])
  }, [panel.id, panel.dialogues])

  useEffect(() => {
    setMaskText(JSON.stringify(JSON.parse(maskSignature), null, 2))
  }, [panel.id, maskSignature])
  const base = `/api/comicreels/panels/${panel.id}/asset`
  const version = encodeURIComponent(panel.updated_at ?? panel.portrait_sha256 ?? panel.status)
  const hasAIPortrait = Boolean(panel.portrait_path && (panel.status === 'AI_IMAGE_READY' || panel.status === 'AI_IMAGE_APPROVED'))
  const hasVisualAnchor = Boolean(panel.visual_anchor?.trim())
  const imageUrl = hasAIPortrait ? `${base}/portrait?v=${version}` : `${base}/crop?v=${version}`

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setWorking(true)
    try { await fn(); setNotice(ok); await reload() }
    catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const saveBbox = () => run(async () => {
    await apiJson(`/api/comicreels/panels/${panel.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ box: bbox, display_order: panel.display_order }),
    })
  }, 'Đã cập nhật vùng cắt. Ảnh sạch, 9:16, approval và storyboard phụ thuộc đã bị hủy.')

  const saveDialogues = () => run(async () => {
    for (let index = 0; index < dialogues.length; index++) {
      const d = dialogues[index]
      if (!d.text && !d.id) continue
      await apiJson(`/api/comicreels/panels/${panel.id}/dialogue`, {
        method: 'PUT',
        body: JSON.stringify({
          id: d.id || null,
          display_order: index,
          speaker_id: d.speaker_id.trim() || 'UNKNOWN',
          text: d.text,
          confidence: d.confidence,
          verified: true,
        }),
      })
    }
  }, 'Đã lưu danh sách thoại theo thứ tự và speaker. Storyboard cũ đã bị hủy.')

  const saveMask = () => run(async () => {
    await apiJson(`/api/comicreels/panels/${panel.id}/mask`, {
      method: 'PUT',
      body: JSON.stringify({ rects: parseMask(maskText) }),
    })
  }, 'Đã sửa vùng chữ/bong bóng AI cần xóa.')

  const removeDialogue = (index: number) => run(async () => {
    const d = dialogues[index]
    if (d.id) await apiJson(`/api/comicreels/dialogues/${d.id}`, { method: 'DELETE' })
    setDialogues(current => current.filter((_, i) => i !== index))
  }, 'Đã xóa lời thoại khỏi panel.')

  const generateAI = () => run(async () => {
    await apiJson(`/api/comicreels/panels/${panel.id}/ai-generate`, {
      method: 'POST',
      body: JSON.stringify({ confirm_paid: true, force: false }),
    })
  }, 'AI đã tạo ảnh sạch 9:16. Hãy xem kỹ trước khi OK.')

  const regenerateAI = () => {
    if (!window.confirm('Tạo lại ảnh AI sẽ dùng thêm một lượt Generate cho khung này. Tiếp tục?')) return
    void run(async () => {
      await apiJson(`/api/comicreels/panels/${panel.id}/ai-generate`, {
        method: 'POST',
        body: JSON.stringify({ confirm_paid: true, force: true }),
      })
    }, 'AI đã tạo lại ảnh 9:16 cho đúng khung này. Hãy review lại trước khi OK.')
  }

  return (
    <article className="rounded-xl border p-4" style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold">Khung {panel.display_order + 1}</div>
          <div className="text-[10px]" style={{ color: 'var(--muted)' }}>
            {panel.w}×{panel.h} · {panel.status}
          </div>
        </div>
        {panel.status === 'AI_IMAGE_APPROVED' && panel.approved_sha256 && panel.approved_sha256 === panel.portrait_sha256
          ? <span className="flex items-center gap-1 text-xs text-green-400"><ShieldCheck size={14}/>Đã OK</span>
          : <span className="text-xs text-amber-400">Chưa duyệt</span>}
      </div>

      <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
        <img src={imageUrl} alt={`Khung ${panel.display_order + 1}`} className="mx-auto max-h-96 max-w-full rounded object-contain" />
      </div>

      {hasAIPortrait && (
        <div className="mt-3 flex flex-wrap items-start gap-3 text-xs">
          <a href={`${base}/portrait?v=${version}`} download={`khung-${panel.display_order + 1}-9x16.png`}
            className="rounded border px-3 py-2" style={{borderColor:'var(--border)'}}><Download size={13} className="mr-1 inline"/>Tải ảnh 9:16</a>
          <details className="flex-1 rounded border p-2" style={{borderColor:'var(--border)'}}>
            <summary className="cursor-pointer">Đối chiếu khung gốc</summary>
            <img src={`${base}/crop?v=${version}`} alt={`Khung gốc ${panel.display_order + 1}`} className="mt-2 max-h-64 w-full object-contain"/>
          </details>
        </div>
      )}

      <div className="mt-3 rounded-lg border p-3" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-semibold">AI nhận diện</span>
          <span className="text-[10px]" style={{ color: 'var(--muted)' }}>{panel.mask.length} vùng chữ / bong bóng</span>
        </div>
        {hasVisualAnchor ? (
          <div className="mt-2 rounded border px-3 py-2 text-[11px]" style={{borderColor:'var(--border)',color:'var(--muted)'}}>
            <strong>Visual anchor:</strong> {panel.visual_anchor}
          </div>
        ) : (
          <div className="mt-2 rounded border px-3 py-2 text-[11px] text-amber-400" style={{borderColor:'var(--border)'}}>
            ⚠ Khung legacy chưa có visual anchor từ ảnh nguồn. Không được Generate/OK cho tới khi backfill anchor.
          </div>
        )}
        <div className="mt-2 space-y-2">
          {panel.dialogues.length === 0 ? (
            <div className="text-xs" style={{ color: 'var(--muted)' }}>Chưa có thoại AI nhận diện.</div>
          ) : panel.dialogues.map((d, index) => (
            <div key={d.id || index} className="rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--border)' }}>
              <div className="flex flex-wrap items-center gap-2">
                <strong>{d.speaker_id}</strong>
                <span style={{ color: 'var(--muted)' }}>→</span>
                <span className="flex-1">{d.text}</span>
                {d.verified
                  ? <span className="rounded-full border px-2 py-0.5 text-[10px] text-green-400" style={{borderColor:'var(--border)'}}>✓ Đã xác nhận</span>
                  : <span className="rounded-full border px-2 py-0.5 text-[10px] text-amber-400" style={{borderColor:'var(--border)'}}>⚠ Cần review</span>}
              </div>
            </div>
          ))}
        </div>
      </div>

      <details className="mt-4 rounded-lg border p-3" style={{ borderColor: 'var(--border)' }}>
        <summary className="cursor-pointer text-xs font-semibold">Sửa nhận diện nếu AI sai</summary>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        {(['x','y','w','h'] as const).map(key => (
          <label key={key} className="text-xs">{key.toUpperCase()}
            <input type="number" min={key === 'w' || key === 'h' ? 1 : 0} value={bbox[key]}
              onChange={e => setBbox(current => ({ ...current, [key]: Number(e.target.value) }))}
              className="mt-1 w-full rounded border px-2 py-2" style={{background:'var(--card)',borderColor:'var(--border)'}}/>
          </label>
        ))}
        <div className="md:col-span-4">
          <button disabled={working} onClick={saveBbox} className="rounded border px-3 py-2 text-xs" style={{borderColor:'var(--border)'}}>
            <Scissors size={14} className="mr-1 inline"/>Lưu vùng cắt
          </button>
        </div>

        <div className="md:col-span-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold">Lời thoại theo thứ tự</span>
            <button className="rounded border px-2 py-1 text-xs" style={{borderColor:'var(--border)'}}
              onClick={() => setDialogues(current => [...current, {
                id:'', panel_id:panel.id, display_order:current.length, speaker_id:`CHAR_${current.length+1}`,
                text:'', verified:0, confidence:null,
              }])}>+ Thêm câu</button>
          </div>
          {dialogues.map((d, index) => (
            <div key={d.id || `new-${index}`} className="grid gap-2 rounded-lg border p-3 md:grid-cols-[140px_1fr_auto]" style={{borderColor:'var(--border)'}}>
              <input value={d.speaker_id} aria-label={`Speaker câu ${index+1}`}
                onChange={e => setDialogues(current => current.map((x,i)=>i===index?{...x,speaker_id:e.target.value}:x))}
                className="rounded border px-2 py-2 text-xs" style={{background:'var(--card)',borderColor:'var(--border)'}}/>
              <textarea value={d.text} rows={2} aria-label={`Lời thoại câu ${index+1}`}
                onChange={e => setDialogues(current => current.map((x,i)=>i===index?{...x,text:e.target.value}:x))}
                className="rounded border px-2 py-2 text-xs" style={{background:'var(--card)',borderColor:'var(--border)'}}/>
              <button onClick={()=>void removeDialogue(index)} className="rounded border px-2" style={{borderColor:'var(--border)'}} title="Xóa câu"><Trash2 size={14}/></button>
            </div>
          ))}
          <button disabled={working} onClick={saveDialogues} className="rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--border)' }}>
            <Save size={14} className="mr-1 inline"/>Lưu toàn bộ thoại
          </button>
        </div>

        <label className="text-xs md:col-span-4">
          Mask chữ / bong bóng (JSON tọa độ trong crop)
          <textarea value={maskText} onChange={e => setMaskText(e.target.value)} rows={4}
            placeholder={'[{"x":20,"y":15,"w":180,"h":90}]'}
            className="mt-1 w-full rounded border px-3 py-2 font-mono text-[11px]"
            style={{ background: 'var(--card)', borderColor: 'var(--border)' }} />
        </label>
        <div className="md:col-span-4">
          <button disabled={working} onClick={saveMask} className="rounded border px-3 py-2 text-xs" style={{ borderColor: 'var(--border)' }}>
            <Save size={14} className="mr-1 inline"/>Lưu vùng AI cần xóa
          </button>
        </div>
      </div>
      </details>

      <div className="mt-3 flex flex-wrap gap-2">
        {!hasAIPortrait ? (
          <button
            disabled={working || !aiConfigured || panel.mask.length === 0 || !hasVisualAnchor}
            onClick={generateAI}
            className="rounded px-3 py-2 text-xs font-semibold disabled:opacity-40"
            style={{ background: 'var(--accent)', color: 'white' }}
          >
            {working ? <Loader2 size={14} className="mr-1 inline animate-spin"/> : <Sparkles size={14} className="mr-1 inline"/>}
            AI Generate ảnh sạch 9:16
          </button>
        ) : (
          <>
            <button
              disabled
              className="rounded px-3 py-2 text-xs font-semibold opacity-60"
              style={{ background: 'var(--accent)', color: 'white' }}
            >
              <CheckCircle2 size={14} className="mr-1 inline"/>Đã có ảnh AI 9:16
            </button>
            <button
              disabled={working || !aiConfigured || !hasVisualAnchor}
              onClick={regenerateAI}
              className="rounded border px-3 py-2 text-xs font-semibold disabled:opacity-40"
              style={{ borderColor: 'var(--border)' }}
            >
              <RefreshCcw size={14} className="mr-1 inline"/>Tạo lại ảnh AI
            </button>
          </>
        )}

        <button disabled={working || !hasAIPortrait || !hasVisualAnchor} onClick={() => run(async () => {
          await apiJson(`/api/comicreels/panels/${panel.id}/approve`, { method: 'POST' })
        }, 'Đã OK đúng hash ảnh AI hiện tại.')}
          className="rounded border px-3 py-2 text-xs font-semibold disabled:opacity-40"
          style={{ borderColor: 'var(--border)' }}>
          <CheckCircle2 size={14} className="mr-1 inline"/>OK ảnh này
        </button>
      </div>
      {!aiConfigured && (
        <div className="mt-2 text-xs text-amber-400">
          AI hình ảnh chưa được kết nối. ComicReels sẽ không dùng compositor kéo-che làm kết quả chính.
        </div>
      )}
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
  const [referencePanelIds, setReferencePanelIds] = useState<string[]>([])
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
    let cancelled = false
    let saved: string | null = null
    try { saved = localStorage.getItem(LAST_PROJECT_KEY) } catch { /* storage may be disabled */ }
    if (saved) {
      void apiJson<Details>(`/api/comicreels/projects/${encodeURIComponent(saved)}`).then(project => {
        if (cancelled) return
        setDetails(project)
        setStep(project.shots.length ? 'video' : project.panels.length ? 'images' : 'analyze')
      }).catch(() => { if (!cancelled) setNotice('Chưa mở lại được dự án gần nhất. Chọn dự án đã lưu để thử lại.') })
    }
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    if (!details?.project.id) return
    try { localStorage.setItem(LAST_PROJECT_KEY, details.project.id) } catch { /* optional convenience */ }
    setPaidConsent(false)
    setFlowProjectId('')
  }, [details?.project.id])
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
      setPendingFile(null)
      setDetails(loaded)
      await refreshProjects()
      if (status?.ai.configured) {
        const analyzed = await apiJson<Details>(`/api/comicreels/projects/${imported.project.id}/analyze`, {
          method: 'POST',
          body: JSON.stringify({ mode: 'ai', confirm_paid: true }),
        })
        setDetails(analyzed)
        setStep('images')
        setNotice(analyzed.analysis_warnings?.length
          ? 'AI đã phân tích và đối chiếu transcript. Có ' + analyzed.analysis_warnings.length + ' cảnh báo cần xem trong gallery.'
          : 'AI đã phân tích và đối chiếu nguyên văn transcript từng khung.')
      } else {
        setDetails(loaded)
        setStep('analyze')
        setNotice('Đã lưu ảnh. Cần kết nối AI để tự nhận diện panel/thoại/speaker.')
      }
      await refreshProjects()
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const analyze = async (mode: 'ai' | 'heuristic') => {
    if (!details) return
    setWorking(true)
    try {
      const next = await apiJson<Details>(`/api/comicreels/projects/${details.project.id}/analyze`, {
        method: 'POST', body: JSON.stringify({ mode, confirm_paid: mode === 'ai' }),
      })
      setDetails(next)
      setStep('images')
      setNotice(mode === 'ai'
        ? (next.analysis_warnings?.length
          ? 'AI đã phân tích và đối chiếu transcript. Có ' + next.analysis_warnings.length + ' cảnh báo cần xem trong gallery.'
          : 'AI đã tự nhận panel/thoại/speaker và đối chiếu nguyên văn từng khung.')
        : 'Fallback local đã tách panel bằng gutter; không tự đọc thoại/speaker.')
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const verifyDialogues = async () => {
    if (!details?.project.ai_conversation_url || !status?.ai.configured) return
    setWorking(true)
    try {
      const next = await apiJson<Details>(`/api/comicreels/projects/${details.project.id}/verify-dialogues`, {
        method: 'POST',
      })
      setDetails(next)
      setNotice('AI đã đọc lại toàn bộ thoại trong chính ChatGPT conversation hiện tại, không upload lại ảnh. Hãy review trước khi xác nhận.')
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      setWorking(false)
    }
  }

  const generateAllImages = async () => {
    if (!details || !status?.ai.configured) return
    const missingAnchors = details.panels.filter(panel => !panel.visual_anchor?.trim())
    if (missingAnchors.length > 0) {
      setNotice(`Có ${missingAnchors.length} khung chưa có visual anchor từ ảnh nguồn. Hãy backfill/re-analyze trước khi Generate.`)
      return
    }
    const pending = details.panels.filter(
      panel => !['AI_IMAGE_READY', 'AI_IMAGE_APPROVED'].includes(panel.status) || !panel.portrait_sha256
    )
    if (pending.length === 0) {
      setNotice('Tất cả khung đã có ảnh AI 9:16. Không gọi Generate lại.')
      return
    }
    setWorking(true)
    try {
      for (const panel of pending) {
        await apiJson(`/api/comicreels/panels/${panel.id}/ai-generate`, {
          method: 'POST',
          body: JSON.stringify({ confirm_paid: true, force: false }),
        })
      }
      const next = await apiJson<Details>(`/api/comicreels/projects/${details.project.id}`)
      setDetails(next)
      setNotice(`AI đã Generate xong ${pending.length} khung còn thiếu. Các khung đã có ảnh được giữ nguyên.`)
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally {
      await reload().catch(() => undefined)
      setWorking(false)
    }
  }

  const storyboard = async () => {
    if (!details) return
    setWorking(true)
    try {
      const next = await apiJson<Details>(`/api/comicreels/projects/${details.project.id}/storyboard`, {
        method: 'POST', body: JSON.stringify({ model_family: 'omni_flash', duration_s: 10 }),
      })
      setDetails(next); setStep('storyboard'); setNotice('Storyboard đã khóa ảnh hash + transcript/speaker được duyệt.')
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setWorking(false) }
  }

  const generateShot = async (shot: Shot, retry = false) => {
    if (!details) return
    if (!paidConsent) { setNotice('Tạo video có thể tốn tín dụng. Tick xác nhận chi phí trước.'); return }
    if (referencePanelIds.length !== REQUIRED_REFERENCES) {
      setNotice('Hãy chọn đúng 3 ảnh đã duyệt làm reference.')
      return
    }
    if (!referencePanelIds.includes(shot.panel_id)) {
      setNotice('Ba ảnh reference phải có ảnh của kịch bản đang chọn.')
      return
    }
    if (retry && !window.confirm('Tạo lại riêng kịch bản này bằng Omni Flash 10s, 360p, 1 phiên bản? Lượt mới có thể tốn tín dụng.')) return
    setWorking(true)
    try {
      await apiJson(`/api/comicreels/shots/${shot.id}/generate-references`, {
        method: 'POST',
        body: JSON.stringify({
          confirm_paid: true,
          idempotency_key: retry ? `retry:${shot.id}:${crypto.randomUUID()}` : `ui:refs:v2:${shot.id}`,
          panel_ids: referencePanelIds,
          project_id: flowProjectId,
          resolution: '360p',
          duration_s: 10,
          variant_count: 1,
          force: retry,
        }),
      })
      setNotice('Đã gửi đúng 1 phiên bản Omni Flash · 10s · 360p với ảnh reference + kịch bản + lời thoại. Không TTS riêng, không tự retry.')
      await reload()
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { await reload().catch(() => undefined); setWorking(false) }
  }

  const pendingImageCount = useMemo(
    () => details?.panels.filter(
      panel => !['AI_IMAGE_READY', 'AI_IMAGE_APPROVED'].includes(panel.status) || !panel.portrait_sha256
    ).length ?? 0,
    [details],
  )

  const allApproved = useMemo(() =>
    Boolean(details?.panels.length) && (details?.panels.every(
      p => Boolean(p.visual_anchor?.trim()) && p.status === 'AI_IMAGE_APPROVED' && p.portrait_sha256 && p.approved_sha256 === p.portrait_sha256
    ) ?? false),
    [details])

  const approvedReferencePanels = useMemo(
    () => details?.panels.filter(
      p => p.status === 'AI_IMAGE_APPROVED' && p.approved_sha256 && p.approved_sha256 === p.portrait_sha256
    ) ?? [],
    [details],
  )
  const requiredReferenceCount = REQUIRED_REFERENCES

  useEffect(() => {
    if (!details?.project.id) {
      setReferencePanelIds([])
      return
    }
    const allowed = new Set(approvedReferencePanels.map(panel => panel.id))
    setReferencePanelIds(current => {
      const kept = current.filter(id => allowed.has(id)).slice(0, requiredReferenceCount)
      if (kept.length === requiredReferenceCount) return kept
      const fill = approvedReferencePanels
        .map(panel => panel.id)
        .filter(id => !kept.includes(id))
        .slice(0, requiredReferenceCount - kept.length)
      return [...kept, ...fill]
    })
  }, [details?.project.id, approvedReferencePanels, requiredReferenceCount])

  return (
    <div className="mx-auto max-w-6xl space-y-5 pb-16" lang="vi">
      <section className="rounded-2xl border p-6" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <div className="flex flex-wrap items-start gap-5">
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold uppercase tracking-[.2em]" style={{ color: 'var(--accent)' }}>ComicReels Studio</div>
            <h1 className="mt-2 text-3xl font-bold">Một ảnh truyện → ảnh 9:16 → video có thoại</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6" style={{ color: 'var(--muted)' }}>
              AI tự nhận panel, thoại, speaker và vùng cần xóa. Khi dựng video, ComicReels gửi 3 ảnh reference + kịch bản thành phần + lời thoại trực tiếp cho Google Flow; không có bước TTS/lồng tiếng tách riêng.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a href="/projects" className="rounded border px-3 py-2 text-xs font-semibold" style={{borderColor:'var(--border)'}}>
                Mở Projects & công cụ video
              </a>
              <a href="/" className="rounded border px-3 py-2 text-xs" style={{borderColor:'var(--border)'}}>
                Dashboard FlowKit
              </a>
            </div>
          </div>
          <div className="space-y-2 rounded-xl border p-3 text-xs" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
            <div>
              <div className="font-semibold">{status?.ai.configured ? '● AI hình ảnh đã kết nối' : '○ AI hình ảnh chưa kết nối'}</div>
              <div className="mt-1" style={{ color: 'var(--muted)' }}>
                {status?.ai.provider ?? 'gpt_fullproxy'} · {status?.ai.image_model ?? 'ChatGPT Create image'}
              </div>
            </div>
            <div className="border-t pt-2" style={{ borderColor: 'var(--border)' }}>
              <div className="font-semibold">{status?.flow.ready ? '● Google Flow sẵn sàng' : '○ Google Flow chưa sẵn sàng'}</div>
              <div className="mt-1" style={{ color: 'var(--muted)' }}>
                Extension: {status?.flow.extension_connected ? 'đã nối' : 'chưa nối'} · Project: {status?.flow.project_id ?? 'chưa chọn'}
              </div>
            </div>
            <button onClick={() => void refreshStatus()} className="rounded border px-2 py-1" style={{ borderColor: 'var(--border)' }}>
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
                {working?<Loader2 size={16} className="mr-1 inline animate-spin"/>:<Save size={16} className="mr-1 inline"/>}{status?.ai.configured ? 'Lưu & AI phân tích' : 'Lưu dự án'}
              </button>
              {pendingFile && <button onClick={()=>setPendingFile(null)} className="rounded border px-3 py-2 text-sm" style={{borderColor:'var(--border)'}}><Trash2 size={15}/></button>}
            </div>
          </div>
        </section>
      )}

      {step === 'analyze' && details && (
        <section className="rounded-2xl border p-5" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
          <h2 className="text-lg font-semibold">AI tự phân tích truyện</h2>
          <p className="mt-1 text-xs" style={{color:'var(--muted)'}}>
            AI tự nhận số khung, thứ tự đọc, nguyên văn thoại, người nói và vùng chữ/bong bóng cần xóa.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              disabled={working || !status?.ai.configured}
              onClick={()=>void analyze('ai')}
              className="rounded px-4 py-2 text-sm font-semibold disabled:opacity-40"
              style={{background:'var(--accent)',color:'white'}}
            >
              {working?<Loader2 size={15} className="mr-1 inline animate-spin"/>:<Sparkles size={15} className="mr-1 inline"/>}
              AI tự nhận diện toàn bộ
            </button>
            <button disabled={working} onClick={()=>void analyze('heuristic')} className="rounded border px-4 py-2 text-sm" style={{borderColor:'var(--border)'}}>
              <Scissors size={15} className="mr-1 inline"/>Fallback tách panel local
            </button>
          </div>
          {!status?.ai.configured && (
            <div className="mt-3 text-xs text-amber-400">
              GPT FullProxy / ChatGPT Web chưa kết nối nên nút nhận diện tự động đang khóa.
            </div>
          )}
          {details.panels.length>0 && <div className="mt-4 text-sm">Đang có <strong>{details.panels.length}</strong> khung. <button className="underline" onClick={()=>setStep('images')}>Mở kết quả AI</button></div>}
        </section>
      )}

      {(step === 'images' || step === 'approve') && details && (
        <section className="space-y-4">
          {details.analysis_warnings && details.analysis_warnings.length > 0 && (
            <div className="rounded-xl border p-4 text-xs text-amber-300" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
              <div className="mb-2 font-semibold">AI transcript có cảnh báo</div>
              <div className="space-y-1">
                {details.analysis_warnings.map((warning, index) => <div key={index}>• {warning}</div>)}
              </div>
            </div>
          )}
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">Gallery {details.panels.length} khung</h2>
                <p className="mt-1 text-xs" style={{color:'var(--muted)'}}>AI đã nhận thoại/speaker/vùng cần xóa. AI Generate sẽ xóa chữ, tái tạo phần bị che và outpaint thẳng thành 9:16.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  disabled={working || !status?.ai.configured || !details.project.ai_conversation_url}
                  onClick={()=>void verifyDialogues()}
                  className="rounded border px-4 py-2 text-sm font-semibold disabled:opacity-40"
                  style={{borderColor:'var(--border)'}}
                >
                  {working?<Loader2 size={15} className="mr-1 inline animate-spin"/>:<RefreshCcw size={15} className="mr-1 inline"/>}
                  AI đọc lại thoại
                </button>
                <button
                  disabled={working || !status?.ai.configured || pendingImageCount === 0 || details.panels.some(p => p.mask.length === 0)}
                  onClick={()=>void generateAllImages()}
                  className="rounded px-4 py-2 text-sm font-semibold disabled:opacity-40"
                  style={{background:'var(--accent)',color:'white'}}
                >
                  {working?<Loader2 size={15} className="mr-1 inline animate-spin"/>:<Sparkles size={15} className="mr-1 inline"/>}
                  {pendingImageCount > 0 ? `AI Generate ${pendingImageCount} khung còn thiếu` : 'Tất cả khung đã có ảnh AI'}
                </button>
              </div>
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {details.panels.map(p => <PanelEditor key={p.id} panel={p} reload={reload} setNotice={setNotice} aiConfigured={Boolean(status?.ai.configured)}/>)}
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
              <div><h2 className="font-semibold">Kịch bản thành phần</h2><p className="text-xs" style={{color:'var(--muted)'}}>Mỗi thành phần giữ nguyên lời thoại và chỉ dẫn diễn xuất. Lời thoại sẽ đi thẳng vào prompt video của Flow, không tạo TTS riêng.</p></div>
              <div className="flex gap-2">
                <button onClick={()=>void storyboard()} disabled={working||!allApproved} className="rounded px-3 py-2 text-sm disabled:opacity-40" style={{background:'var(--accent)',color:'white'}}><Film size={15} className="mr-1 inline"/>Tạo kịch bản thành phần</button>
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
          {details.shots.length>0 && <button onClick={()=>setStep('video')} className="rounded px-4 py-2 text-sm" style={{background:'var(--accent)',color:'white'}}>Sang 3 ảnh + kịch bản → Flow</button>}
        </section>
      )}

      {step === 'video' && details && (
        <section className="space-y-4">
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <h2 className="font-semibold">3 ảnh reference + kịch bản thành phần → Google Flow</h2>
            <p className="mt-1 text-xs" style={{color:'var(--muted)'}}>
              Chọn 3 ảnh đã duyệt để khóa nhân vật/hình dáng/trang phục. Sau đó chọn một kịch bản thành phần bên dưới; ComicReels upload các ảnh reference và gửi nguyên kịch bản kèm lời thoại cho Flow. Không có bước TTS riêng.
            </p>
            <div className="mt-3 inline-flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold" style={{borderColor:'var(--accent)',color:'var(--text)'}}>
              <span>Omni Flash</span><span>·</span><span>10s</span><span>·</span><span>360p</span><span>·</span><span>1 phiên bản</span>
            </div>
            <div className="mt-1 text-[10px]" style={{color:'var(--muted)'}}>Credit do Google Flow quyết định tại thời điểm gửi; ComicReels không hardcode mức 7 credit.</div>
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between gap-2 text-xs">
                <strong>Ảnh reference đã chọn: {referencePanelIds.length}/{requiredReferenceCount}</strong>
                <span style={{color:'var(--muted)'}}>{approvedReferencePanels.length < 3 ? 'Cần đủ 3 ảnh đã duyệt để tạo video theo quy trình này.' : 'Chọn đúng 3 ảnh, gồm ảnh của kịch bản cần tạo.'}</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {approvedReferencePanels.map(panel => {
                  const selected = referencePanelIds.includes(panel.id)
                  return (
                    <button key={panel.id} type="button"
                      onClick={() => setReferencePanelIds(current => {
                        if (selected) return current.filter(id => id !== panel.id)
                        if (current.length >= requiredReferenceCount) return current
                        return [...current, panel.id]
                      })}
                      className="rounded-lg border p-2 text-left"
                      style={{borderColor:selected?'var(--accent)':'var(--border)',background:'var(--card)'}}>
                      <img src={`/api/comicreels/panels/${panel.id}/asset/portrait?v=${encodeURIComponent(panel.portrait_sha256 ?? '')}`}
                        className="mx-auto h-44 w-full rounded object-contain" alt={`Reference khung ${panel.display_order + 1}`}/>
                      <div className="mt-2 flex items-center justify-between text-xs">
                        <span>Khung {panel.display_order + 1}</span>
                        <span style={{color:selected?'var(--accent)':'var(--muted)'}}>{selected?'✓ Đã chọn':'Chọn'}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
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
            <article key={s.id} className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1"><strong className="text-sm">Kịch bản {s.display_order+1}</strong><div className="truncate text-xs" style={{color:'var(--muted)'}}>{s.dialogue_text||'Cảnh phản ứng im lặng'} · Omni Flash · {s.duration_s}s · 360p · 1 bản · {s.status}</div></div>
                <button disabled={working || !paidConsent || !status?.flow.ready || referencePanelIds.length !== REQUIRED_REFERENCES || !referencePanelIds.includes(s.panel_id) || !(['READY', 'PENDING', 'FAILED'].includes(s.status) || (s.status === 'COMPLETED' && s.review_status === 'REJECTED'))}
                  onClick={()=>void generateShot(s, s.status === 'FAILED' || s.review_status === 'REJECTED')} className="rounded border px-3 py-2 text-xs disabled:opacity-40" style={{borderColor:'var(--border)'}}>
                  <Play size={14} className="mr-1 inline"/>{s.status === 'FAILED' || s.review_status === 'REJECTED' ? 'Tạo lại riêng kịch bản này' : 'Tạo 1 bản Omni Flash 10s · 360p'}
                </button>
                <button disabled={working || !['PROCESSING', 'SUBMISSION_UNKNOWN'].includes(s.status)} onClick={async()=>{
                setWorking(true)
                try{await apiJson(`/api/comicreels/shots/${s.id}/poll`,{method:'POST'});setNotice('Đã cập nhật trạng thái video.');await reload()}catch(e){setNotice(e instanceof Error?e.message:String(e))}finally{setWorking(false)}
              }} className="rounded border px-3 py-2 text-xs disabled:opacity-40" style={{borderColor:'var(--border)'}}>Kiểm tra trạng thái</button>
              </div>
              {!referencePanelIds.includes(s.panel_id) && <p className="mt-2 text-xs text-amber-400">Chọn ảnh của khung này trong bộ 3 reference trước khi tạo.</p>}
              {['SUBMITTING', 'SUBMISSION_UNKNOWN'].includes(s.status) && <p className="mt-2 text-xs text-amber-400">Đang gửi hoặc chưa nhận đủ phản hồi từ Flow. Kiểm tra trạng thái trên Flow trước; ComicReels giữ khóa để tránh tạo trùng.</p>}
              {s.flow_payload?.error && <p className="mt-2 text-xs text-amber-400">{s.flow_payload.error}</p>}
              {s.video_path && s.status === 'COMPLETED' && (
                <div className="mt-3 space-y-2">
                  <video controls preload="metadata" className="mx-auto max-h-[32rem] w-full rounded bg-black"
                    src={`/api/comicreels/shots/${s.id}/video?v=${encodeURIComponent(s.updated_at ?? '')}`}/>
                  <a className="inline-block rounded border px-3 py-2 text-xs" style={{borderColor:'var(--border)'}}
                    href={`/api/comicreels/shots/${s.id}/video`} download={`comicreels-shot-${s.display_order + 1}.mp4`}>Tải video này</a>
                </div>
              )}
              <details className="mt-3 rounded border p-3" style={{borderColor:'var(--border)'}}>
                <summary className="cursor-pointer text-xs font-semibold">Xem kịch bản + lời thoại sẽ gửi sang Flow</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-[11px]" style={{color:'var(--muted)'}}>{s.prompt}</pre>
              </details>
            </article>
          ))}
          <div className="rounded-xl border p-4" style={{background:'var(--surface)',borderColor:'var(--border)'}}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <strong className="text-sm">Review & ghép Reel</strong>
                <div className="mt-1 text-xs" style={{color:'var(--muted)'}}>Duyệt từng file video sau khi xem/nghe. Chỉ ghép khi tất cả shot APPROVED.</div>
              </div>
              <a className="rounded border px-3 py-2 text-xs" style={{borderColor:'var(--border)'}}
                href={`/api/comicreels/projects/${details.project.id}/assemble`}
                onClick={e => {
                  if (!details.shots.length || !details.shots.every(s=>s.video_path && s.review_status==='APPROVED')) {
                    e.preventDefault(); setNotice('Chưa thể ghép: mọi shot phải có video local và được APPROVED.')
                  }
                }}>Ghép Reel đã duyệt</a>
            </div>
            <div className="mt-3 space-y-2">
              {details.shots.filter(s=>s.video_path && s.status === 'COMPLETED').map(s=>(
                <div key={s.id} className="flex flex-wrap items-center gap-2 rounded border p-2 text-xs" style={{borderColor:'var(--border)'}}>
                  <span className="font-semibold">Shot {s.display_order+1}</span>
                  <span style={{color:'var(--muted)'}}>Xem và nghe video ở phía trên trước khi duyệt.</span>
                  <span className="ml-auto">{s.review_status}</span>
                  <button className="rounded border px-2 py-1" style={{borderColor:'var(--border)'}} disabled={working} onClick={async()=>{
                    setWorking(true)
                    try { await apiJson(`/api/comicreels/shots/${s.id}/review`,{method:'PUT',body:JSON.stringify({status:'APPROVED',video_path:s.video_path,notes:'Đã duyệt từ ComicReels Studio.'})}); await reload() }
                    catch(e) { setNotice(e instanceof Error ? e.message : String(e)) } finally { setWorking(false) }
                  }}>Duyệt</button>
                  <button className="rounded border px-2 py-1" style={{borderColor:'var(--border)'}} disabled={working} onClick={async()=>{
                    setWorking(true)
                    try { await apiJson(`/api/comicreels/shots/${s.id}/review`,{method:'PUT',body:JSON.stringify({status:'REJECTED',video_path:s.video_path,notes:'Cần tạo lại shot.'})}); await reload(); setNotice('Đã đánh dấu lỗi. Dùng nút Tạo lại riêng kịch bản này ở phía trên.') }
                    catch(e) { setNotice(e instanceof Error ? e.message : String(e)) } finally { setWorking(false) }
                  }}>Lỗi / tạo lại</button>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-xl border p-4 text-xs" style={{background:'var(--surface)',borderColor:'var(--border)',color:'var(--muted)'}}>
            ComicReels chỉ gửi từng kịch bản thành phần sau khi anh chọn ảnh reference và xác nhận chi phí. Lời thoại nằm ngay trong prompt video; tuyến này không tạo hoặc ghép file TTS riêng. Giao diện gửi từng video; các công cụ hàng loạt của FlowKit vẫn nằm trong Projects.
          </div>
        </section>
      )}
    </div>
  )
}
