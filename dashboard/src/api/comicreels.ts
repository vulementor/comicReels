export interface ComicCharacter {
  id: string
  project_id: string
  stable_key: string
  name: string
  description?: string | null
}

export interface ComicDialogue {
  id: string
  panel_id: string
  sequence: number
  speaker_id: string | null
  verbatim_text: string
  confidence?: number | null
  bbox?: { x: number; y: number; width: number; height: number } | null
  user_verified: boolean
}

export interface ComicShot {
  id: string
  panel_id: string
  display_order: number
  speaker_id: string | null
  verbatim_text: string
  duration_s: number
  model_family: 'omni_flash' | 'veo'
  prompt: string
  image_sha256: string
  status: string
  review_status: 'PENDING' | 'APPROVED' | 'REJECTED'
}

export interface ComicPanel {
  id: string
  project_id: string
  display_order: number
  x: number
  y: number
  width: number
  height: number
  confidence?: number | null
  crop_path?: string | null
  mask_path?: string | null
  clean_path?: string | null
  vertical_path?: string | null
  vertical_sha256?: string | null
  approved_sha256?: string | null
  status: string
  dialogues: ComicDialogue[]
  shots: ComicShot[]
}

export interface ComicGeneration {
  id: string
  project_id: string
  shot_id: string
  idempotency_key: string
  model_family: string
  duration_s: number
  resolution: string
  cost_estimate?: number | null
  cost_approved: boolean
  status: string
  video_path?: string | null
  error_message?: string | null
}

export interface ComicProject {
  id: string
  name: string
  status: string
  source_sha256: string
  source_mime: string
  source_width: number
  source_height: number
  analysis_provider?: string | null
  panels: ComicPanel[]
  characters: ComicCharacter[]
  generations: ComicGeneration[]
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) {
    const raw = await response.text()
    let message = raw
    try {
      const parsed = JSON.parse(raw)
      message = parsed.detail ?? raw
    } catch {
      // keep raw response
    }
    throw new Error(message || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function importComic(file: File, name: string): Promise<ComicProject> {
  const form = new FormData()
  form.append('file', file)
  form.append('name', name)
  return api('/api/comicreels/projects/import', { method: 'POST', body: form })
}

export async function restoreComic(file: File): Promise<ComicProject> {
  const form = new FormData()
  form.append('file', file)
  return api('/api/comicreels/projects/restore', { method: 'POST', body: form })
}

export const comic = {
  listProjects: () => api<ComicProject[]>('/api/comicreels/projects'),
  getProject: (id: string) => api<ComicProject>(`/api/comicreels/projects/${id}`),
  analyze: (id: string, useVision = true, replaceExisting = false) =>
    api<ComicProject>(`/api/comicreels/projects/${id}/analyze`, {
      method: 'POST', body: JSON.stringify({ use_vision: useVision, replace_existing: replaceExisting }),
    }),
  patchPanel: (panelId: string, data: unknown) =>
    api<ComicPanel>(`/api/comicreels/panels/${panelId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  saveDialogues: (panelId: string, dialogues: unknown[]) =>
    api<ComicDialogue[]>(`/api/comicreels/panels/${panelId}/dialogues`, {
      method: 'PUT', body: JSON.stringify({ dialogues }),
    }),
  processPanel: (panelId: string, boxes?: unknown[]) =>
    api<ComicPanel>(`/api/comicreels/panels/${panelId}/process`, {
      method: 'POST', body: JSON.stringify({ boxes: boxes ?? null, padding: 8, inpaint_radius: 5 }),
    }),
  processAll: (projectId: string) =>
    api<ComicProject>(`/api/comicreels/projects/${projectId}/process-all`, { method: 'POST' }),
  approve: (panelId: string, sha: string) =>
    api<ComicPanel>(`/api/comicreels/panels/${panelId}/approve`, {
      method: 'POST', body: JSON.stringify({ expected_sha256: sha }),
    }),
  planShots: (projectId: string, modelFamily: 'omni_flash' | 'veo') =>
    api<ComicShot[]>(`/api/comicreels/projects/${projectId}/plan-shots`, {
      method: 'POST', body: JSON.stringify({ model_family: modelFamily, words_per_second: 2.6 }),
    }),
  queueBatch: (projectId: string, shotIds: string[], family: 'omni_flash' | 'veo', batchKey: string) =>
    api<ComicGeneration[]>(`/api/comicreels/projects/${projectId}/generations/batch`, {
      method: 'POST',
      body: JSON.stringify({
        shot_ids: shotIds, batch_key: batchKey, confirm_cost: true, model_family: family, resolution: '720p',
      }),
    }),
  queueOne: (projectId: string, shot: ComicShot, key: string) =>
    api<ComicGeneration>(`/api/comicreels/projects/${projectId}/generations`, {
      method: 'POST',
      body: JSON.stringify({
        shot_id: shot.id, idempotency_key: key, confirm_cost: true,
        model_family: shot.model_family, duration_s: shot.duration_s, resolution: '720p',
      }),
    }),
  review: (shotId: string, reviewStatus: 'PENDING' | 'APPROVED' | 'REJECTED') =>
    api<ComicShot>(`/api/comicreels/shots/${shotId}/review`, {
      method: 'PATCH', body: JSON.stringify({ review_status: reviewStatus }),
    }),
  cost: (shotId: string) =>
    api<{ estimated_credits: number | null; note: string }>(`/api/comicreels/shots/${shotId}/cost`),
}

export const comicUrl = {
  source: (projectId: string) => `/api/comicreels/projects/${projectId}/source`,
  asset: (panelId: string, kind: 'crop' | 'mask' | 'clean' | 'vertical', stamp?: string | number) =>
    `/api/comicreels/panels/${panelId}/asset/${kind}${stamp ? `?v=${encodeURIComponent(stamp)}` : ''}`,
  video: (generationId: string) => `/api/comicreels/generations/${generationId}/video`,
  manualExport: (projectId: string) => `/api/comicreels/projects/${projectId}/export/manual`,
  backup: (projectId: string) => `/api/comicreels/projects/${projectId}/backup`,
}

export async function downloadPost(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { method: 'POST' })
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
