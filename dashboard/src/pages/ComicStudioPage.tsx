import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Check, CheckCircle2, Copy, Download, Film, FolderOpen, ImagePlus, MessageSquare, Play, Plus, RefreshCcw, Save, ScanLine, Scissors, ShieldCheck, Upload, WifiOff, X } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { comic, comicUrl, downloadPost, importComic, restoreComic, type ComicGeneration, type ComicPanel, type ComicProject, type ComicShot } from '../api/comicreels'

type Health = { status?: string; extension_connected?: boolean }
type FlowStatus = { connected?: boolean; flow_project_id?: string | null; session_project?: { project_id?: string | null } | null }
type DraftDialogue = {
  id?: string
  speaker_id?: string | null
  speaker_name?: string
  verbatim_text: string
  user_verified: boolean
  bbox?: { x: number; y: number; width: number; height: number } | null
}

const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
const MAX_IMAGE_BYTES = 30 * 1024 * 1024

function btn(disabled = false) {
  return 'inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold ' +
    (disabled ? 'cursor-not-allowed opacity-40' : 'hover:opacity-85')
}

function lastGeneration(gens: ComicGeneration[], shotId: string) {
  return gens.filter(g => g.shot_id === shotId).at(-1)
}

function PanelEditor(props: {
  project: ComicProject
  panel: ComicPanel
  busy: boolean
  run: (name: string, action: () => Promise<unknown>) => Promise<void>
  reload: () => Promise<void>
}) {
  const { project, panel, busy, run, reload } = props
  const [box, setBox] = useState({ x: panel.x, y: panel.y, width: panel.width, height: panel.height })
  const [dialogues, setDialogues] = useState<DraftDialogue[]>([])
  const [localError, setLocalError] = useState('')

  useEffect(() => {
    setBox({ x: panel.x, y: panel.y, width: panel.width, height: panel.height })
    setDialogues(panel.dialogues.map(d => ({
      id: d.id,
      speaker_id: d.speaker_id,
      verbatim_text: d.verbatim_text,
      user_verified: d.user_verified,
      bbox: d.bbox ? { ...d.bbox } : null,
    })))
  }, [panel])

  const approved = !!panel.vertical_sha256 && panel.approved_sha256 === panel.vertical_sha256
  const missingBbox = dialogues.some(d => !d.bbox)

  const patchDialogue = (index: number, patch: Partial<DraftDialogue>) => {
    setDialogues(rows => rows.map((row, i) => i === index ? { ...row, ...patch } : row))
  }

  const patchDialogueBox = (index: number, key: 'x' | 'y' | 'width' | 'height', value: string) => {
    const current = dialogues[index].bbox || { x: 0, y: 0, width: 1, height: 1 }
    patchDialogue(index, { bbox: { ...current, [key]: Math.max(0, Number(value) || 0) } })
  }

  const savePanel = async () => {
    await run('Lưu vùng panel', async () => {
      await comic.patchPanel(panel.id, { bbox: box })
      await reload()
    })
  }

  const saveDialogues = async () => {
    setLocalError('')
    const payload = dialogues.map((d, sequence) => ({
      id: d.id,
      sequence,
      speaker_id: d.speaker_id || undefined,
      speaker_name: !d.speaker_id ? d.speaker_name?.trim() || undefined : undefined,
      verbatim_text: d.verbatim_text,
      bbox: d.bbox || undefined,
      user_verified: d.user_verified,
    }))
    if (payload.some(d => !d.verbatim_text.trim())) {
      setLocalError('Không được lưu dòng thoại trống.')
      return
    }
    if (payload.some(d => !d.speaker_id && !d.speaker_name)) {
      setLocalError('Mỗi câu thoại cần một người nói.')
      return
    }
    await run('Lưu thoại', async () => {
      await comic.saveDialogues(panel.id, payload)
      await reload()
    })
  }

  const processPanel = async () => {
    if (missingBbox && dialogues.length) {
      setLocalError('Mỗi câu thoại cần bbox bong bóng để tạo mask chính xác.')
      return
    }
    await run('Xử lý ảnh panel', async () => {
      await comic.processPanel(panel.id)
      await reload()
    })
  }

  const approvePanel = async () => {
    if (!panel.vertical_sha256) return
    await run('Duyệt ảnh 9:16', async () => {
      await comic.approve(panel.id, panel.vertical_sha256 as string)
      await reload()
    })
  }

  const asset = (kind: 'crop' | 'mask' | 'clean' | 'vertical') => {
    const exists = kind === 'crop' ? panel.crop_path : kind === 'mask' ? panel.mask_path : kind === 'clean' ? panel.clean_path : panel.vertical_path
    return exists ? (
      <img src={comicUrl.asset(panel.id, kind, panel.vertical_sha256 || panel.status)} alt={kind} className="max-h-96 w-full rounded-lg border object-contain" style={{ borderColor: 'var(--border)', background: 'var(--bg)' }} />
    ) : (
      <div className="flex min-h-40 items-center justify-center rounded-lg border text-xs" style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}>Chưa có ảnh</div>
    )
  }

  return (
    <section className="rounded-2xl border p-4 sm:p-5" style={{ borderColor: approved ? 'var(--green)' : 'var(--border)', background: 'var(--surface)' }}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-bold">Khung {panel.display_order + 1}</h3>
        <span className="rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}>{panel.status}</span>
        {approved && <span className="inline-flex items-center gap-1 text-[11px]" style={{ color: 'var(--green)' }}><ShieldCheck size={14} />Đã OK đúng phiên bản</span>}
        {panel.confidence != null && <span className="ml-auto text-[10px]" style={{ color: 'var(--muted)' }}>confidence {Math.round(panel.confidence * 100)}%</span>}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        {(['x', 'y', 'width', 'height'] as const).map(key => (
          <label key={key} className="text-[10px] uppercase" style={{ color: 'var(--muted)' }}>
            {key}
            <input
              type="number"
              min="0"
              value={box[key]}
              onChange={e => setBox(v => ({ ...v, [key]: Math.max(0, Number(e.target.value) || 0) }))}
              className="mt-1 w-full rounded border px-2 py-2 text-xs"
              style={{ background: 'var(--card)', borderColor: 'var(--border)' }}
            />
          </label>
        ))}
        <div className="flex items-end"><button type="button" disabled={busy} onClick={() => void savePanel()} className={btn(busy) + ' w-full border'} style={{ borderColor: 'var(--border)' }}><Save size={14} />Lưu khung</button></div>
      </div>

      <div className="mt-4 rounded-xl border p-4" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
        <div className="flex flex-wrap items-center gap-2">
          <MessageSquare size={15} />
          <h4 className="font-semibold">Thoại và người nói</h4>
          <button type="button" className={btn() + ' ml-auto border'} style={{ borderColor: 'var(--border)' }} onClick={() => setDialogues(rows => [...rows, { speaker_id: null, speaker_name: '', verbatim_text: '', user_verified: false, bbox: null }])}><Plus size={13} />Thêm câu</button>
        </div>
        {dialogues.length === 0 && <p className="mt-3 text-xs" style={{ color: 'var(--muted)' }}>Cảnh im lặng có thể để trống.</p>}
        <div className="mt-3 flex flex-col gap-3">
          {dialogues.map((d, index) => (
            <div key={d.id || String(index)} className="rounded-lg border p-3" style={{ borderColor: 'var(--border)' }}>
              <div className="grid gap-2 lg:grid-cols-[170px_1fr_auto]">
                <div>
                  <select
                    value={d.speaker_id || '__new__'}
                    onChange={e => patchDialogue(index, { speaker_id: e.target.value === '__new__' ? null : e.target.value })}
                    className="w-full rounded border px-2 py-2 text-xs"
                    style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
                  >
                    <option value="__new__">Nhập tên mới…</option>
                    {project.characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                  {!d.speaker_id && <input value={d.speaker_name || ''} onChange={e => patchDialogue(index, { speaker_name: e.target.value })} placeholder="Tên nhân vật" className="mt-1 w-full rounded border px-2 py-2 text-xs" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }} />}
                </div>
                <textarea value={d.verbatim_text} onChange={e => patchDialogue(index, { verbatim_text: e.target.value })} rows={3} className="w-full rounded border px-3 py-2 text-sm" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }} placeholder="Nguyên văn lời thoại" />
                <div className="flex items-start gap-2">
                  <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={d.user_verified} onChange={e => patchDialogue(index, { user_verified: e.target.checked })} />Đã kiểm tra</label>
                  <button type="button" onClick={() => setDialogues(rows => rows.filter((_, i) => i !== index))} className="rounded border p-1.5" style={{ borderColor: 'var(--border)' }}><X size={13} /></button>
                </div>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {(['x', 'y', 'width', 'height'] as const).map(key => (
                  <label key={key} className="text-[10px] uppercase" style={{ color: 'var(--muted)' }}>
                    bubble {key}
                    <input type="number" min="0" value={d.bbox?.[key] ?? ''} onChange={e => patchDialogueBox(index, key, e.target.value)} className="mt-1 w-full rounded border px-2 py-1.5 text-xs" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }} />
                  </label>
                ))}
                <button type="button" onClick={() => patchDialogue(index, { bbox: null })} className={btn() + ' self-end border'} style={{ borderColor: 'var(--border)' }}>Bỏ bbox</button>
              </div>
            </div>
          ))}
        </div>
        {localError && <p className="mt-3 text-xs" style={{ color: 'var(--red)' }}>{localError}</p>}
        <button type="button" disabled={busy} onClick={() => void saveDialogues()} className={btn(busy) + ' mt-3'} style={{ background: 'var(--accent)', color: 'white' }}><Save size={13} />Lưu thoại</button>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={busy || (missingBbox && dialogues.length > 0)} onClick={() => void processPanel()} className={btn(busy || (missingBbox && dialogues.length > 0))} style={{ background: 'var(--accent)', color: 'white' }}><Scissors size={14} />Xóa chữ + tạo 9:16</button>
        <button type="button" disabled={busy || !panel.vertical_sha256 || approved} onClick={() => void approvePanel()} className={btn(busy || !panel.vertical_sha256 || approved) + ' border'} style={{ borderColor: approved ? 'var(--green)' : 'var(--border)' }}><Check size={14} />{approved ? 'Đã OK' : 'OK ảnh này'}</button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div><p className="mb-1 text-[10px] uppercase" style={{ color: 'var(--muted)' }}>Crop</p>{asset('crop')}</div>
        <div><p className="mb-1 text-[10px] uppercase" style={{ color: 'var(--muted)' }}>Mask</p>{asset('mask')}</div>
        <div><p className="mb-1 text-[10px] uppercase" style={{ color: 'var(--muted)' }}>Ảnh sạch</p>{asset('clean')}</div>
        <div><p className="mb-1 text-[10px] uppercase" style={{ color: 'var(--muted)' }}>9:16</p>{asset('vertical')}</div>
      </div>
    </section>
  )
}

function ShotView(props: {
  project: ComicProject
  shot: ComicShot
  confirmCost: boolean
  busy: boolean
  run: (name: string, action: () => Promise<unknown>) => Promise<void>
  reload: () => Promise<void>
}) {
  const { project, shot, confirmCost, busy, run, reload } = props
  const gen = lastGeneration(project.generations, shot.id)
  const [copied, setCopied] = useState(false)

  const queue = async () => {
    await run('Xếp một video', async () => {
      await comic.queueOne(project.id, shot, 'comicreels:' + project.id + ':' + shot.id + ':' + shot.image_sha256 + ':' + (project.generations.filter(g => g.shot_id === shot.id).length + 1))
      await reload()
    })
  }

  const review = async (value: 'APPROVED' | 'REJECTED') => {
    await run('Lưu đánh giá', async () => {
      await comic.review(shot.id, value)
      await reload()
    })
  }

  const copy = async () => {
    await navigator.clipboard.writeText(shot.prompt)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1000)
  }

  return (
    <article className="rounded-xl border p-4" style={{ borderColor: shot.review_status === 'APPROVED' ? 'var(--green)' : 'var(--border)', background: 'var(--card)' }}>
      <div className="flex flex-wrap items-center gap-2">
        <b>Shot {shot.display_order + 1} · {shot.duration_s}s</b>
        <span className="rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: 'var(--border)' }}>{shot.model_family}</span>
        <span className="ml-auto text-[10px]" style={{ color: gen?.status === 'FAILED' ? 'var(--red)' : 'var(--muted)' }}>video: {gen?.status || 'chưa tạo'}</span>
      </div>
      {shot.verbatim_text && <blockquote className="mt-2 rounded border-l-2 px-3 py-2 text-sm" style={{ borderColor: 'var(--accent)', background: 'var(--surface)' }}>{shot.verbatim_text}</blockquote>}
      <pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded border p-3 text-[11px] leading-5" style={{ borderColor: 'var(--border)', background: 'var(--surface)', color: 'var(--muted)' }}>{shot.prompt}</pre>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={() => void copy()} className={btn() + ' border'} style={{ borderColor: 'var(--border)' }}><Copy size={13} />{copied ? 'Đã chép' : 'Chép prompt'}</button>
        <button type="button" disabled={busy || !confirmCost || ['QUEUED', 'PROCESSING'].includes(gen?.status || '')} onClick={() => void queue()} className={btn(busy || !confirmCost)} style={{ background: 'var(--accent)', color: 'white' }}><Play size={13} />Tạo video này</button>
      </div>
      {gen?.error_message && <p className="mt-2 text-xs" style={{ color: 'var(--red)' }}>{gen.error_message}</p>}
      {gen?.status === 'COMPLETED' && (
        <div className="mt-4">
          <video src={comicUrl.video(gen.id)} controls className="max-h-[560px] w-full rounded-lg bg-black" />
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => void review('APPROVED')} className={btn(busy)} style={{ background: 'var(--green)', color: '#07110b' }}><Check size={14} />Video đạt</button>
            <button type="button" disabled={busy} onClick={() => void review('REJECTED')} className={btn(busy) + ' border'} style={{ borderColor: 'var(--red)', color: 'var(--red)' }}><X size={14} />Tạo lại</button>
          </div>
        </div>
      )}
    </article>
  )
}

export default function ComicStudioPage() {
  const [projects, setProjects] = useState<ComicProject[]>([])
  const [project, setProject] = useState<ComicProject | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [name, setName] = useState('ComicReels')
  const [useVision, setUseVision] = useState(true)
  const [modelFamily, setModelFamily] = useState<'omni_flash' | 'veo'>('omni_flash')
  const [confirmCost, setConfirmCost] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [health, setHealth] = useState<Health | null>(null)
  const [flow, setFlow] = useState<FlowStatus | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const restoreInput = useRef<HTMLInputElement>(null)

  const refreshProjects = useCallback(async () => {
    const rows = await comic.listProjects()
    setProjects(rows)
  }, [])

  const load = useCallback(async (id: string) => {
    setProject(await comic.getProject(id))
  }, [])

  const refreshConnection = useCallback(async () => {
    try {
      const h = await fetchAPI<Health>('/health')
      setHealth(h)
      setFlow(h.extension_connected ? await fetchAPI<FlowStatus>('/api/flow/status') : null)
    } catch {
      setHealth(null)
      setFlow(null)
    }
  }, [])

  useEffect(() => {
    void refreshProjects()
    void refreshConnection()
    const timer = window.setInterval(() => void refreshConnection(), 15000)
    return () => window.clearInterval(timer)
  }, [refreshProjects, refreshConnection])

  useEffect(() => {
    if (!project?.generations.some(g => ['QUEUED', 'PROCESSING'].includes(g.status))) return
    const timer = window.setInterval(() => void load(project.id), 3000)
    return () => window.clearInterval(timer)
  }, [project, load])

  useEffect(() => {
    if (!file) { setPreview(null); return }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const run = useCallback(async (label: string, action: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true)
    setError('')
    setMessage(label + '…')
    try {
      await action()
      setMessage(label + ': hoàn tất.')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setMessage('')
    } finally {
      setBusy(false)
    }
  }, [busy])

  const acceptFile = useCallback((value?: File) => {
    if (!value) return
    if (!IMAGE_TYPES.has(value.type)) { setError('Chỉ hỗ trợ PNG, JPG/JPEG hoặc WebP.'); return }
    if (!value.size || value.size > MAX_IMAGE_BYTES) { setError('Ảnh phải từ 1 byte đến 30 MB.'); return }
    setFile(value)
    setError('')
    if (name === 'ComicReels') setName(value.name.replace(/\.[^.]+$/, '') || 'ComicReels')
  }, [name])

  useEffect(() => {
    const paste = (e: ClipboardEvent) => {
      const target = e.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA'].includes(target.tagName))) return
      const pasted = Array.from(e.clipboardData?.items || []).find(x => x.kind === 'file' && x.type.startsWith('image/'))?.getAsFile()
      if (pasted) { e.preventDefault(); acceptFile(pasted) }
    }
    window.addEventListener('paste', paste)
    return () => window.removeEventListener('paste', paste)
  }, [acceptFile])

  const flowReady = !!health?.extension_connected && !!flow?.connected && !!(flow.flow_project_id || flow.session_project?.project_id)
  const allApproved = !!project?.panels.length && project.panels.every(p => !!p.vertical_sha256 && p.vertical_sha256 === p.approved_sha256)
  const dialoguesVerified = project?.panels.every(p => p.dialogues.every(d => d.user_verified && !!d.speaker_id)) || false
  const shots = useMemo(() => project?.panels.flatMap(p => p.shots) || [], [project])
  const videosApproved = shots.length > 0 && shots.every(s => s.review_status === 'APPROVED' && lastGeneration(project?.generations || [], s.id)?.status === 'COMPLETED')

  const importFile = async () => {
    if (!file) return
    await run('Lưu ảnh gốc', async () => {
      const created = await importComic(file, name.trim() || 'ComicReels')
      await refreshProjects()
      await load(created.id)
      setFile(null)
    })
  }

  const restore = async (value?: File) => {
    if (!value) return
    await run('Khôi phục backup', async () => {
      const restored = await restoreComic(value)
      await refreshProjects()
      await load(restored.id)
    })
  }

  const analyze = async () => {
    if (!project) return
    await run('Phân tích truyện', async () => {
      setProject(await comic.analyze(project.id, useVision, project.panels.length > 0))
      await refreshProjects()
    })
  }

  const movePanel = async (panelId: string, delta: number) => {
    if (!project) return
    const ordered = [...project.panels].sort((a, b) => a.display_order - b.display_order)
    const index = ordered.findIndex(p => p.id === panelId)
    const target = index + delta
    if (index < 0 || target < 0 || target >= ordered.length) return
    const next = [...ordered]
    ;[next[index], next[target]] = [next[target], next[index]]
    await run('Đổi thứ tự đọc', async () => {
      await comic.reorderPanels(project.id, next.map(p => p.id))
      await load(project.id)
    })
  }

  const plan = async () => {
    if (!project) return
    await run('Tạo shot và prompt', async () => {
      await comic.planShots(project.id, modelFamily)
      await load(project.id)
    })
  }

  const queueAll = async () => {
    if (!project || !shots.length || !confirmCost) return
    await run('Xếp toàn bộ video', async () => {
      await comic.queueBatch(project.id, shots.map(s => s.id), modelFamily, 'batch:' + project.id + ':' + Date.now())
      await load(project.id)
    })
  }

  const concat = async () => {
    if (!project) return
    await run('Ghép Reel', () => downloadPost('/api/comicreels/projects/' + project.id + '/concat', project.name + '-final.mp4'))
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5 pb-16" lang="vi">
      <section className="rounded-2xl border p-5 sm:p-7" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-[.22em]" style={{ color: 'var(--accent)' }}>ComicReels Studio</div>
            <h1 className="mt-2 text-3xl font-bold">Một ảnh truyện → ảnh 9:16 → video</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6" style={{ color: 'var(--muted)' }}>Ảnh xử lý local. Thoại và speaker phải xác minh, ảnh phải OK đúng hash rồi mới tạo prompt. Flow chỉ dùng khi tạo video.</p>
          </div>
          {project && <a href={comicUrl.backup(project.id)} className={btn() + ' border no-underline'} style={{ borderColor: 'var(--border)', color: 'var(--text)' }}><Download size={14} />Backup</a>}
          <input ref={restoreInput} type="file" accept=".zip,application/zip" className="sr-only" onChange={e => { void restore(e.target.files?.[0]); e.target.value = '' }} />
          <button type="button" onClick={() => restoreInput.current?.click()} className={btn() + ' border'} style={{ borderColor: 'var(--border)' }}><FolderOpen size={14} />Khôi phục</button>
        </div>
      </section>

      <section className="rounded-xl border p-4" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
        <div className="flex flex-wrap items-center gap-3">
          {flowReady ? <CheckCircle2 size={18} style={{ color: 'var(--green)' }} /> : health ? <AlertCircle size={18} style={{ color: 'var(--yellow)' }} /> : <WifiOff size={18} style={{ color: 'var(--yellow)' }} />}
          <div>
            <b className="text-sm">{flowReady ? 'Google Flow sẵn sàng cho video' : health?.extension_connected ? 'Extension đã nối, Flow/project chưa sẵn sàng' : health ? 'Backend hoạt động, Extension chưa kết nối' : 'Backend chưa kết nối'}</b>
            <p className="text-[11px]" style={{ color: 'var(--muted)' }}>Xử lý ảnh và xuất prompt vẫn hoạt động khi Flow offline.</p>
          </div>
          <button type="button" onClick={() => void refreshConnection()} className={btn() + ' ml-auto border'} style={{ borderColor: 'var(--border)' }}><RefreshCcw size={13} />Kiểm tra lại</button>
        </div>
      </section>

      {(message || error) && <div className="rounded-xl border p-3 text-sm" style={{ borderColor: error ? 'var(--red)' : 'var(--border)', color: error ? 'var(--red)' : 'var(--text)' }}>{error || message}</div>}

      <div className="grid gap-5 xl:grid-cols-[300px_1fr]">
        <aside className="flex flex-col gap-4">
          <section className="rounded-2xl border p-4" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-2"><ImagePlus size={16} /><b>Ảnh nguồn</b></div>
            <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={e => { acceptFile(e.target.files?.[0]); e.target.value = '' }} />
            <div className="mt-3 flex min-h-48 flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-3 text-center" style={{ borderColor: 'var(--border)', background: 'var(--card)' }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); acceptFile(e.dataTransfer.files[0]) }}>
              {preview ? <img src={preview} className="max-h-56 max-w-full rounded object-contain" alt="preview" /> : <Upload size={34} style={{ color: 'var(--accent)' }} />}
              <span className="text-xs" style={{ color: 'var(--muted)' }}>{file ? file.name : 'Ctrl+V, kéo thả hoặc chọn ảnh'}</span>
              <button type="button" onClick={() => fileInput.current?.click()} className={btn() + ' border'} style={{ borderColor: 'var(--border)' }}>Chọn ảnh</button>
            </div>
            <input value={name} onChange={e => setName(e.target.value)} className="mt-3 w-full rounded border px-3 py-2 text-sm" style={{ background: 'var(--card)', borderColor: 'var(--border)' }} />
            <button type="button" disabled={busy || !file} onClick={() => void importFile()} className={btn(busy || !file) + ' mt-2 w-full'} style={{ background: 'var(--accent)', color: 'white' }}><Save size={14} />Lưu ảnh gốc</button>
          </section>

          <section className="rounded-2xl border p-4" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-2"><FolderOpen size={16} /><b>Dự án</b></div>
            <div className="mt-3 flex max-h-72 flex-col gap-2 overflow-auto">
              {projects.map(p => <button key={p.id} type="button" onClick={() => void load(p.id)} className="rounded-lg border p-3 text-left" style={{ borderColor: project?.id === p.id ? 'var(--accent)' : 'var(--border)', background: 'var(--card)' }}><p className="truncate text-xs font-semibold">{p.name}</p><p className="mt-1 text-[10px]" style={{ color: 'var(--muted)' }}>{p.status}</p></button>)}
            </div>
          </section>
        </aside>

        <main className="min-w-0">
          {!project ? (
            <section className="flex min-h-[520px] items-center justify-center rounded-2xl border p-8 text-center" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}><div><Film size={42} className="mx-auto" style={{ color: 'var(--accent)' }} /><h2 className="mt-3 text-xl font-bold">Chọn hoặc nhập một truyện</h2></div></section>
          ) : (
            <div className="flex flex-col gap-5">
              <section className="rounded-2xl border p-4 sm:p-5" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
                <div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-bold">{project.name}</h2><span className="text-[11px]" style={{ color: 'var(--muted)' }}>{project.source_width}×{project.source_height} · {project.status}</span><a href={comicUrl.source(project.id)} target="_blank" rel="noreferrer" className={btn() + ' ml-auto border no-underline'} style={{ borderColor: 'var(--border)', color: 'var(--text)' }}><Download size={13} />Ảnh gốc</a></div>
                <div className="mt-4 grid gap-4 lg:grid-cols-[260px_1fr]">
                  <img src={comicUrl.source(project.id)} className="max-h-80 w-full rounded-lg border object-contain" style={{ borderColor: 'var(--border)', background: 'var(--bg)' }} alt="source" />
                  <div>
                    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={useVision} onChange={e => setUseVision(e.target.checked)} />Dùng Vision đọc thoại/người nói</label>
                    <button type="button" disabled={busy} onClick={() => void analyze()} className={btn(busy) + ' mt-3'} style={{ background: 'var(--accent)', color: 'white' }}><ScanLine size={14} />{project.panels.length ? 'Phân tích lại' : 'Phân tích truyện'}</button>
                    <p className="mt-3 text-xs leading-5" style={{ color: 'var(--muted)' }}>Vision chỉ gợi ý. Nếu không có API key, detector local vẫn tách panel và anh nhập thoại thủ công.</p>
                  </div>
                </div>
              </section>

              {project.panels.length > 1 && (
                <section className="rounded-2xl border p-4" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
                  <div className="flex items-center gap-2"><ScanLine size={15} /><h3 className="font-bold">Thứ tự đọc</h3><span className="text-[11px]" style={{ color: 'var(--muted)' }}>Sửa trước khi xử lý ảnh để khung và thoại đi đúng mạch truyện.</span></div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {[...project.panels].sort((a,b) => a.display_order - b.display_order).map((p, index, ordered) => (
                      <div key={p.id} className="flex items-center gap-1 rounded-lg border px-2 py-1.5" style={{ borderColor: 'var(--border)', background: 'var(--card)' }}>
                        <span className="min-w-16 text-xs font-semibold">Khung {index + 1}</span>
                        <button type="button" disabled={busy || index === 0} onClick={() => void movePanel(p.id, -1)} className={btn(busy || index === 0) + ' border px-2 py-1'} style={{ borderColor: 'var(--border)' }} aria-label={`Đưa khung ${index + 1} lên trước`}>↑</button>
                        <button type="button" disabled={busy || index === ordered.length - 1} onClick={() => void movePanel(p.id, 1)} className={btn(busy || index === ordered.length - 1) + ' border px-2 py-1'} style={{ borderColor: 'var(--border)' }} aria-label={`Đưa khung ${index + 1} xuống sau`}>↓</button>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {project.panels.map(p => <PanelEditor key={p.id} project={project} panel={p} busy={busy} run={run} reload={() => load(project.id)} />)}

              <section className="rounded-2xl border p-4 sm:p-5" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
                <div className="flex flex-wrap items-center gap-2">
                  <div><h3 className="text-lg font-bold">Prompt và shot</h3><p className="text-xs" style={{ color: 'var(--muted)' }}>Chỉ mở sau khi mọi ảnh đã OK và thoại/speaker được xác minh.</p></div>
                  <select value={modelFamily} onChange={e => setModelFamily(e.target.value as 'omni_flash' | 'veo')} className="ml-auto rounded border px-3 py-2 text-xs" style={{ background: 'var(--card)', borderColor: 'var(--border)' }}><option value="omni_flash">Omni Flash</option><option value="veo">Veo</option></select>
                  <button type="button" disabled={busy || !allApproved || !dialoguesVerified} onClick={() => void plan()} className={btn(busy || !allApproved || !dialoguesVerified)} style={{ background: 'var(--accent)', color: 'white' }}><MessageSquare size={14} />Tạo prompt</button>
                  <a href={comicUrl.manualExport(project.id)} className={btn(!allApproved || !shots.length) + ' border no-underline'} style={{ pointerEvents: !allApproved || !shots.length ? 'none' : undefined, borderColor: 'var(--border)', color: 'var(--text)' }}><Download size={14} />Gói Flow thủ công</a>
                </div>
                {!allApproved && <p className="mt-3 text-xs" style={{ color: 'var(--yellow)' }}>Cần OK toàn bộ ảnh 9:16 trước khi tạo prompt.</p>}
                <div className="mt-4 flex flex-col gap-3">
                  {project.panels.map(panel => panel.shots.length ? <div key={panel.id} className="rounded-xl border p-3" style={{ borderColor: 'var(--border)' }}><b>Khung {panel.display_order + 1}</b><div className="mt-3 grid gap-3 xl:grid-cols-2">{panel.shots.map(s => <ShotView key={s.id} project={project} shot={s} confirmCost={confirmCost} busy={busy} run={run} reload={() => load(project.id)} />)}</div></div> : null)}
                </div>
              </section>

              <section className="rounded-2xl border p-4 sm:p-5" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
                <div className="flex flex-wrap items-center gap-3">
                  <div><h3 className="text-lg font-bold">Google Flow và thành phẩm</h3><p className="text-xs" style={{ color: 'var(--muted)' }}>Không gửi job nếu anh chưa xác nhận tín dụng.</p></div>
                  <label className="ml-auto flex items-center gap-2 rounded-lg border px-3 py-2 text-xs" style={{ borderColor: confirmCost ? 'var(--green)' : 'var(--border)' }}><input type="checkbox" checked={confirmCost} onChange={e => setConfirmCost(e.target.checked)} />Xác nhận video có thể tốn tín dụng</label>
                  <button type="button" disabled={busy || !flowReady || !confirmCost || !shots.length} onClick={() => void queueAll()} className={btn(busy || !flowReady || !confirmCost || !shots.length)} style={{ background: 'var(--accent)', color: 'white' }}><Play size={14} />Xếp toàn bộ shot</button>
                  <button type="button" disabled={busy} onClick={() => void run('Tạm dừng queue', () => comic.pauseQueue())} className={btn(busy) + ' border'} style={{ borderColor: 'var(--border)' }}>Tạm dừng queue</button>
                  <button type="button" disabled={busy} onClick={() => void run('Tiếp tục queue', () => comic.resumeQueue())} className={btn(busy) + ' border'} style={{ borderColor: 'var(--border)' }}>Tiếp tục queue</button>
                  <button type="button" disabled={busy || !videosApproved} onClick={() => void concat()} className={btn(busy || !videosApproved) + ' border'} style={{ borderColor: videosApproved ? 'var(--green)' : 'var(--border)' }}><Film size={14} />Ghép Reel</button>
                </div>
                {project.generations.length > 0 && <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs"><thead style={{ color: 'var(--muted)' }}><tr><th className="py-2">Job</th><th>Shot</th><th>Model</th><th>Giây</th><th>Credits ước tính</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{project.generations.map(g => <tr key={g.id} className="border-t" style={{ borderColor: 'var(--border)' }}><td className="py-2 font-mono">{g.id.slice(0, 8)}</td><td className="font-mono">{g.shot_id.slice(0, 8)}</td><td>{g.model_family}</td><td>{g.duration_s}</td><td>{g.cost_estimate ?? 'xem Flow'}</td><td style={{ color: g.status === 'FAILED' ? 'var(--red)' : g.status === 'COMPLETED' ? 'var(--green)' : 'var(--text)' }}>{g.status}</td><td>{g.status === 'QUEUED' ? <button type="button" disabled={busy} onClick={() => void run('Hủy job', async () => { await comic.cancelGeneration(g.id); await load(project.id) })} className={btn(busy) + ' border py-1'} style={{ borderColor: 'var(--red)', color: 'var(--red)' }}>Hủy job</button> : <span style={{ color: 'var(--muted)' }}>—</span>}</td></tr>)}</tbody></table></div>}
              </section>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
