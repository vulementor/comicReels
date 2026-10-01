import { useState, useEffect } from 'react'
import { fetchAPI } from '../api/client'
import { useWebSocketContext } from '../api/useWebSocketContext'
import { useTranslation } from '../i18n/useTranslation'
import type { TranslationKey } from '../i18n/translations'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/card'
import { Badge } from '../components/ui/badge'

interface HealthResponse {
  status: string
  version: string
  transport: 'browser'
  backend_ready: boolean | null
  browser_session_ready: boolean | null
  authentication: 'authenticated' | 'signed_out' | 'unknown' | null
  lease_held: boolean | null
  reconciliation_required: boolean | null
  pending_intents: number | null
  paid_dispatch_enabled: boolean | null
}

function useHealthPoll() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [reachable, setReachable] = useState(true)

  useEffect(() => {
    let cancelled = false
    function poll() {
      fetchAPI<HealthResponse>('/health')
        .then(h => { if (!cancelled) { setHealth(h); setReachable(true) } })
        .catch(() => { if (!cancelled) { setHealth(null); setReachable(false) } })
    }
    Promise.resolve().then(poll)
    const id = setInterval(poll, 4000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return { health, reachable }
}

const STEP_KEYS: { titleKey: TranslationKey; bodyKey: TranslationKey }[] = [
  { titleKey: 'guide.step1.title', bodyKey: 'guide.step1.body' },
  { titleKey: 'guide.step2.title', bodyKey: 'guide.step2.body' },
  { titleKey: 'guide.step3.title', bodyKey: 'guide.step3.body' },
  { titleKey: 'guide.step4.title', bodyKey: 'guide.step4.body' },
]

const TROUBLE_KEYS: { problemKey: TranslationKey; solutionKey: TranslationKey }[] = [
  { problemKey: 'guide.trouble1.problem', solutionKey: 'guide.trouble1.solution' },
  { problemKey: 'guide.trouble2.problem', solutionKey: 'guide.trouble2.solution' },
  { problemKey: 'guide.trouble3.problem', solutionKey: 'guide.trouble3.solution' },
  { problemKey: 'guide.trouble4.problem', solutionKey: 'guide.trouble4.solution' },
  { problemKey: 'guide.trouble5.problem', solutionKey: 'guide.trouble5.solution' },
  { problemKey: 'guide.trouble6.problem', solutionKey: 'guide.trouble6.solution' },
]

export default function GuidePage() {
  const { t } = useTranslation()
  const { isConnected: dashboardConnected } = useWebSocketContext()
  const { health, reachable } = useHealthPoll()

  const browserReady = health?.backend_ready === true
    && health.browser_session_ready === true
    && health.authentication === 'authenticated'
    && health.lease_held === true
  const paidLocked = health?.paid_dispatch_enabled === false

  return (
    <div className="flex flex-col gap-5 max-w-3xl">
      <div>
        <h1 className="m-0 text-lg font-semibold" style={{ color: 'var(--text)' }}>{t('guide.title')}</h1>
        <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{t('guide.intro')}</p>
      </div>

      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase">{t('guide.status.title')}</CardTitle>
          <CardDescription className="text-[11px]">{t('guide.status.desc')}</CardDescription>
        </CardHeader>
        <CardContent>
          {!reachable ? (
            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--red)' }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--red)' }} />
              {t('guide.status.unreachable')}
            </div>
          ) : !health ? (
            <div className="text-xs" style={{ color: 'var(--muted)' }}>{t('guide.status.checking')}</div>
          ) : (
            <div className="flex flex-col gap-2 text-xs">
              <div className="flex flex-wrap gap-6">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--green)' }} />
                  <span style={{ color: 'var(--text)' }}>{t('guide.status.agentRunning')}</span>
                  <Badge variant="outline">v{health.version}</Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ background: browserReady ? 'var(--green)' : 'var(--red)' }}
                  />
                  <span style={{ color: browserReady ? 'var(--green)' : 'var(--red)' }}>
                    {browserReady ? t('guide.status.browserReady') : t('guide.status.browserNotReady')}
                  </span>
                </div>
              </div>

              <div style={{ color: 'var(--muted)' }}>
                {t('guide.status.authentication')}: {health.authentication === 'authenticated'
                  ? t('guide.status.authenticated')
                  : health.authentication === 'signed_out'
                    ? t('guide.status.signedOut')
                    : t('guide.status.unknown')}
                {' · '}
                {t('guide.status.lease')}: {health.lease_held === true
                  ? t('guide.status.leaseHeld')
                  : health.lease_held === false
                    ? t('guide.status.leaseMissing')
                    : t('guide.status.unknown')}
              </div>

              <div style={{ color: health.reconciliation_required === true ? 'var(--accent)' : 'var(--muted)' }}>
                {t('guide.status.reconciliation')}: {health.reconciliation_required === true
                  ? t('guide.status.reconciliationRequired', { n: health.pending_intents ?? 0 })
                  : t('guide.status.reconciliationClear')}
              </div>

              <div style={{ color: paidLocked ? 'var(--muted)' : 'var(--accent)' }}>
                {t('guide.status.paidDispatch')}: {health.paid_dispatch_enabled === true
                  ? t('guide.status.paidValidation')
                  : paidLocked
                    ? t('guide.status.paidLocked')
                    : t('guide.status.unknown')}
              </div>

              <div style={{ color: 'var(--muted)' }}>
                {t('guide.status.dashboardChannel')}: {dashboardConnected
                  ? t('guide.status.dashboardLive')
                  : t('guide.status.dashboardOffline')}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        {STEP_KEYS.map((s, i) => (
          <Card key={s.titleKey} className="py-4">
            <CardContent>
              <div className="flex gap-3.5">
                <span
                  className="flex-shrink-0 flex items-center justify-center rounded-full text-xs font-semibold"
                  style={{ width: 22, height: 22, background: 'var(--accent)', color: 'var(--bg)' }}
                >
                  {i + 1}
                </span>
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{t(s.titleKey)}</span>
                  <span className="text-[11px] leading-relaxed" style={{ color: 'var(--muted)' }}>{t(s.bodyKey)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase">{t('guide.trouble.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3">
            {TROUBLE_KEYS.map(tr => (
              <div key={tr.problemKey} className="flex flex-col gap-0.5 pb-3" style={{ borderBottom: '1px solid var(--border)' }}>
                <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>{t(tr.problemKey)}</span>
                <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{t(tr.solutionKey)}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
