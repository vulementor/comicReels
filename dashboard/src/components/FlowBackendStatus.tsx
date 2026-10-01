import { useEffect, useState } from 'react'
import { fetchAPI } from '../api/client'
import { useTranslation } from '../i18n/useTranslation'

type BackendStatus = {
  schema_version: 1
  backend_kind: 'browser' | 'extension' | 'unknown'
  backend_selection_source: string
  backend_ready: boolean
  paid_dispatch_enabled: boolean | null
  reconciliation_required: boolean | null
  error: string | null
  preflight: { ready: boolean; extension_required: boolean | null }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function decodeStatus(value: unknown): BackendStatus {
  if (!isRecord(value) || value.schema_version !== 1
    || !['browser', 'extension', 'unknown'].includes(String(value.backend_kind))
    || typeof value.backend_ready !== 'boolean'
    || !(value.paid_dispatch_enabled === null || typeof value.paid_dispatch_enabled === 'boolean')
    || !(value.reconciliation_required === null || typeof value.reconciliation_required === 'boolean')
    || typeof value.backend_selection_source !== 'string'
    || !(value.error === null || typeof value.error === 'string')
    || !isRecord(value.preflight) || typeof value.preflight.ready !== 'boolean'
    || !(value.preflight.extension_required === null || typeof value.preflight.extension_required === 'boolean')) {
    throw new Error('BACKEND_STATUS_INVALID')
  }
  return {
    schema_version: 1,
    backend_kind: value.backend_kind as BackendStatus['backend_kind'],
    backend_selection_source: value.backend_selection_source,
    backend_ready: value.backend_ready,
    paid_dispatch_enabled: value.paid_dispatch_enabled,
    reconciliation_required: value.reconciliation_required,
    error: value.error,
    preflight: {
      ready: value.preflight.ready,
      extension_required: value.preflight.extension_required,
    },
  }
}

const WORDS = {
  vi: {
    title: 'Backend Flow', checking: 'Đang đọc trạng thái', unavailable: 'Không đọc được trạng thái',
    unknown: 'Chưa rõ', ready: 'Sẵn sàng', notReady: 'Chưa sẵn sàng',
    paid: 'Kênh trả phí', enabled: 'Bật', disabled: 'Tắt',
    explicit: 'Được chọn trong cấu hình', original: 'Mặc định extension',
    candidate: 'Theo cấu hình mặc định browser', unrecorded: 'Chưa ghi nhận nguồn lựa chọn',
    warning: 'Có tác vụ cần đối soát', browserPreflight: 'Không yêu cầu extension',
    extensionPreflight: 'Yêu cầu kết nối extension', restart: 'Đổi backend cần khởi động lại',
    note: 'Trạng thái không xác nhận nghiệm thu hoặc cấp quyền tạo nội dung.',
  },
  en: {
    title: 'Flow backend', checking: 'Reading status', unavailable: 'Status unavailable',
    unknown: 'Unknown', ready: 'Ready', notReady: 'Not ready',
    paid: 'Paid dispatch', enabled: 'Enabled', disabled: 'Disabled',
    explicit: 'Explicit configuration', original: 'Extension default',
    candidate: 'Configured browser default', unrecorded: 'Selection source not recorded',
    warning: 'Reconciliation required', browserPreflight: 'Extension not required',
    extensionPreflight: 'Extension connection required', restart: 'Backend changes require restart',
    note: 'Status does not prove acceptance or authorize generation.',
  },
}

const UNOBSERVED = new Set([
  'READINESS_TIMEOUT', 'READINESS_UNAVAILABLE', 'BACKEND_NOT_INITIALIZED', 'BROWSER_QUEUE_FULL',
])

export default function FlowBackendStatus() {
  const { lang } = useTranslation()
  const words = lang === 'vi' ? WORDS.vi : WORDS.en
  const [status, setStatus] = useState<BackendStatus | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  useEffect(() => {
    let disposed = false
    let next: number | undefined
    let controller: AbortController | null = null

    async function refresh() {
      const request = new AbortController()
      controller = request
      const deadline = window.setTimeout(() => request.abort(), 5000)
      try {
        const raw = await fetchAPI<unknown>('/api/flow/backend-status', {
          signal: request.signal, cache: 'no-store',
        })
        const current = decodeStatus(raw)
        if (!disposed) {
          setStatus(current)
          setUnavailable(false)
        }
      } catch {
        if (!disposed) {
          // Never leave stale green readiness visible after a failed observation.
          setStatus(null)
          setUnavailable(true)
        }
      } finally {
        window.clearTimeout(deadline)
        // Schedule after completion, not with an overlapping polling interval.
        if (!disposed) next = window.setTimeout(() => { void refresh() }, 15000)
      }
    }
    void refresh()
    return () => {
      disposed = true
      window.clearTimeout(next)
      controller?.abort()
    }
  }, [])

  const kind = status?.backend_kind === 'browser' ? 'Browser'
    : status?.backend_kind === 'extension' ? 'Extension' : words.unknown
  const notObserved = !status || (status.error !== null && UNOBSERVED.has(status.error))
  const ready = !notObserved && status?.backend_ready === true && status.preflight.ready === true
  const stateLabel = notObserved ? words.unknown : ready ? words.ready : words.notReady
  const source = status?.backend_selection_source === 'explicit' ? words.explicit
    : status?.backend_selection_source === 'extension_default' ? words.original
      : status?.backend_selection_source === 'accepted_browser_default' ? words.candidate : words.unrecorded
  const paid = status?.paid_dispatch_enabled === true ? words.enabled
    : status?.paid_dispatch_enabled === false ? words.disabled : words.unknown

  return (
    <section aria-label={words.title} className="flex flex-col gap-1 text-[10px] leading-relaxed" style={{ color: 'var(--muted)' }}>
      <div className="font-semibold" style={{ color: 'var(--text)' }}>{words.title}: {kind}</div>
      <div role="status" aria-live="polite" className="flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{ background: notObserved ? 'var(--muted)' : ready ? 'var(--green)' : 'var(--red)' }} />
        {status ? stateLabel : unavailable ? words.unavailable : words.checking}
      </div>
      <div>{source}</div>
      <div>{words.paid}: {paid}</div>
      {status?.reconciliation_required === true && <div style={{ color: 'var(--accent)' }}>{words.warning}</div>}
      {status?.preflight.extension_required === false && <div>{words.browserPreflight}</div>}
      {status?.preflight.extension_required === true && <div>{words.extensionPreflight}</div>}
      <div>{words.restart}</div>
      <div>{words.note}</div>
    </section>
  )
}
