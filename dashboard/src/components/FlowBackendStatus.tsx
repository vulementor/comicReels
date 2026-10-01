import { useEffect, useState } from 'react'
import { fetchAPI } from '../api/client'
import { useTranslation } from '../i18n/useTranslation'

type BackendStatus = {
  schema_version: 2
  backend_kind: 'browser'
  backend_selection_source: 'browser_only' | 'unrecorded'
  backend_ready: boolean
  session_ready: boolean | null
  authentication: 'authenticated' | 'signed_out' | 'unknown' | null
  lease_held: boolean | null
  pending_intents: number | null
  paid_dispatch_enabled: boolean | null
  reconciliation_required: boolean | null
  error: string | null
  preflight: {
    ready: boolean
    transport: 'browser'
    session_required: true
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === 'boolean'
}

function decodeStatus(value: unknown): BackendStatus {
  if (!isRecord(value)
    || value.schema_version !== 2
    || value.backend_kind !== 'browser'
    || !['browser_only', 'unrecorded'].includes(String(value.backend_selection_source))
    || typeof value.backend_ready !== 'boolean'
    || !nullableBoolean(value.session_ready)
    || ![null, 'authenticated', 'signed_out', 'unknown'].includes(value.authentication as null | string)
    || !nullableBoolean(value.lease_held)
    || !(value.pending_intents === null
      || (typeof value.pending_intents === 'number'
        && Number.isInteger(value.pending_intents)
        && value.pending_intents >= 0))
    || !nullableBoolean(value.paid_dispatch_enabled)
    || !nullableBoolean(value.reconciliation_required)
    || !(value.error === null || typeof value.error === 'string')
    || !isRecord(value.preflight)
    || typeof value.preflight.ready !== 'boolean'
    || value.preflight.transport !== 'browser'
    || value.preflight.session_required !== true) {
    throw new Error('BACKEND_STATUS_INVALID')
  }

  return {
    schema_version: 2,
    backend_kind: 'browser',
    backend_selection_source: value.backend_selection_source as BackendStatus['backend_selection_source'],
    backend_ready: value.backend_ready,
    session_ready: value.session_ready as boolean | null,
    authentication: value.authentication as BackendStatus['authentication'],
    lease_held: value.lease_held as boolean | null,
    pending_intents: value.pending_intents as number | null,
    paid_dispatch_enabled: value.paid_dispatch_enabled as boolean | null,
    reconciliation_required: value.reconciliation_required as boolean | null,
    error: value.error,
    preflight: {
      ready: value.preflight.ready,
      transport: 'browser',
      session_required: true,
    },
  }
}

const WORDS = {
  vi: {
    title: 'Flow Browser',
    checking: 'Đang đọc trạng thái',
    unavailable: 'Không đọc được trạng thái',
    unknown: 'Chưa rõ',
    ready: 'Sẵn sàng',
    notReady: 'Chưa sẵn sàng',
    session: 'Phiên browser',
    authenticated: 'Đã đăng nhập',
    signedOut: 'Chưa đăng nhập',
    lease: 'Profile lease',
    held: 'Đang giữ',
    notHeld: 'Chưa giữ',
    reconciliation: 'Đối soát',
    reconciliationClear: 'Không có tác vụ chờ',
    reconciliationRequired: 'Cần đối soát',
    pending: 'tác vụ chưa xác định',
    paid: 'Paid dispatch',
    paidLocked: 'Đang khóa',
    paidValidation: 'Đã bật cho validation',
    browserOnly: 'Transport browser-only',
    unrecorded: 'Chưa ghi nhận nguồn lựa chọn',
    restart: 'Thay đổi transport cần khởi động lại',
    note: 'Browser sẵn sàng không đồng nghĩa được cấp quyền chạy tác vụ trả phí.',
  },
  en: {
    title: 'Flow Browser',
    checking: 'Reading status',
    unavailable: 'Status unavailable',
    unknown: 'Unknown',
    ready: 'Ready',
    notReady: 'Not ready',
    session: 'Browser session',
    authenticated: 'Signed in',
    signedOut: 'Signed out',
    lease: 'Profile lease',
    held: 'Held',
    notHeld: 'Not held',
    reconciliation: 'Reconciliation',
    reconciliationClear: 'No pending items',
    reconciliationRequired: 'Required',
    pending: 'unresolved item(s)',
    paid: 'Paid dispatch',
    paidLocked: 'Locked',
    paidValidation: 'Validation enabled',
    browserOnly: 'Browser-only transport',
    unrecorded: 'Selection source not recorded',
    restart: 'Transport changes require restart',
    note: 'Browser readiness does not authorize paid generation.',
  },
}

const UNOBSERVED = new Set([
  'READINESS_TIMEOUT',
  'READINESS_UNAVAILABLE',
  'BACKEND_NOT_INITIALIZED',
  'BROWSER_QUEUE_FULL',
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
          signal: request.signal,
          cache: 'no-store',
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

  const notObserved = !status || (status.error !== null && UNOBSERVED.has(status.error))
  const ready = !notObserved
    && status.backend_ready === true
    && status.preflight.ready === true
    && status.session_ready === true
    && status.authentication === 'authenticated'
    && status.lease_held === true

  const stateLabel = notObserved ? words.unknown : ready ? words.ready : words.notReady
  const sessionLabel = status?.session_ready === true
    ? words.ready
    : status?.session_ready === false ? words.notReady : words.unknown
  const authLabel = status?.authentication === 'authenticated'
    ? words.authenticated
    : status?.authentication === 'signed_out' ? words.signedOut : words.unknown
  const leaseLabel = status?.lease_held === true
    ? words.held
    : status?.lease_held === false ? words.notHeld : words.unknown
  const sourceLabel = status?.backend_selection_source === 'browser_only'
    ? words.browserOnly
    : words.unrecorded

  const paidLocked = status?.paid_dispatch_enabled === false
  const paidLabel = status?.paid_dispatch_enabled === true
    ? words.paidValidation
    : paidLocked ? words.paidLocked : words.unknown

  const pending = status?.pending_intents
  const reconciliationLabel = status?.reconciliation_required === true
    ? `${words.reconciliationRequired}${typeof pending === 'number' ? ` · ${pending} ${words.pending}` : ''}`
    : status?.reconciliation_required === false ? words.reconciliationClear : words.unknown

  return (
    <section
      aria-label={words.title}
      className="flex flex-col gap-1 text-[10px] leading-relaxed"
      style={{ color: 'var(--muted)' }}
    >
      <div className="font-semibold" style={{ color: 'var(--text)' }}>{words.title}</div>
      <div role="status" aria-live="polite" className="flex items-center gap-1.5">
        <span
          className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{
            background: notObserved ? 'var(--muted)' : ready ? 'var(--green)' : 'var(--red)',
          }}
        />
        {status ? stateLabel : unavailable ? words.unavailable : words.checking}
      </div>
      <div>{sourceLabel}</div>
      <div>{words.session}: {sessionLabel} · {authLabel}</div>
      <div>{words.lease}: {leaseLabel}</div>
      <div style={{ color: status?.reconciliation_required === true ? 'var(--accent)' : 'var(--muted)' }}>
        {words.reconciliation}: {reconciliationLabel}
      </div>
      <div style={{ color: paidLocked ? 'var(--muted)' : status?.paid_dispatch_enabled === true ? 'var(--accent)' : 'var(--muted)' }}>
        {words.paid}: {paidLabel}
      </div>
      <div>{words.restart}</div>
      <div>{words.note}</div>
    </section>
  )
}
