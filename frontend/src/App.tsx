import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { mockApi } from './mockApi'
import { SEED_PROPERTIES } from './seedProperties'

type Property = {
  id: number
  name: string
  price: number
  available: boolean
  city?: string
  beds?: number
}

type Reservation = {
  reservation_id: string
  property_id: number
  property_name?: string
  guest_name: string
  amount: number
  payment_id?: string
  refund_id?: string
  status?: string
  created_at?: string
  cancelled_at?: string
}

type BookResult = {
  status: string
  message?: string
  reservation?: Reservation
  payment?: {
    status: string
    payment_id?: string
    message?: string
  }
  refund?: {
    status: string
    refund_id?: string
    message?: string
  }
}

type LogEntry = {
  file: string
  line: string
}

const API_BASE = import.meta.env.VITE_API_URL ?? ''
const FORCE_DEMO =
  import.meta.env.VITE_DEMO_MODE === 'true' || import.meta.env.VITE_DEMO_MODE === '1'

const CARD_HUES = [210, 160, 30, 280, 190, 340, 120, 45, 250, 15, 200, 300]

async function liveApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
    ...options,
  })
  const data = await res.json()
  return data as T
}

async function detectDemoMode(): Promise<boolean> {
  if (FORCE_DEMO) return true
  // Production static deploy (GitHub Pages) has no local gateway.
  if (import.meta.env.PROD) {
    try {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 1200)
      const res = await fetch(`${API_BASE}/api/health`, { signal: controller.signal })
      clearTimeout(timer)
      if (!res.ok) return true
      const data = (await res.json()) as { status?: string }
      return data.status !== 'ok'
    } catch {
      return true
    }
  }
  // Dev: try health; fall back to mock if gateway is down.
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 800)
    const res = await fetch(`${API_BASE}/api/health`, { signal: controller.signal })
    clearTimeout(timer)
    if (!res.ok) return true
    const data = (await res.json()) as { status?: string }
    return data.status !== 'ok'
  } catch {
    return true
  }
}

function App() {
  const [demoMode, setDemoMode] = useState(FORCE_DEMO || Boolean(import.meta.env.PROD))
  const [modeReady, setModeReady] = useState(FORCE_DEMO)
  const [properties, setProperties] = useState<Property[]>([])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [guestName, setGuestName] = useState('Tom')
  const [bookingId, setBookingId] = useState<number | null>(null)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [result, setResult] = useState<BookResult | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [logsOpen, setLogsOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [availableOnly, setAvailableOnly] = useState(false)
  const [minBeds, setMinBeds] = useState('')
  const [selected, setSelected] = useState<Property | null>(null)
  const [resetting, setResetting] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const demo = await detectDemoMode()
      if (!cancelled) {
        setDemoMode(demo)
        setModeReady(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const loadProperties = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (demoMode) {
        const data = mockApi.listProperties()
        setProperties(data.properties)
        return
      }
      const data = await liveApi<{ status: string; properties?: Property[]; message?: string }>(
        '/api/properties',
      )
      if (data.status !== 'success' || !data.properties) {
        throw new Error(data.message ?? 'Failed to load properties')
      }
      setProperties(data.properties)
    } catch (err) {
      // If live fails unexpectedly, fall back to seed so the UI still works.
      setProperties(SEED_PROPERTIES.map((p) => ({ ...p })))
      setDemoMode(true)
      setError(err instanceof Error ? err.message : 'Failed to load properties — switched to demo mode')
    } finally {
      setLoading(false)
    }
  }, [demoMode])

  const loadReservations = useCallback(async () => {
    try {
      if (demoMode) {
        setReservations(mockApi.listReservations().reservations)
        return
      }
      const data = await liveApi<{ status: string; reservations?: Reservation[] }>('/api/reservations')
      setReservations(data.reservations ?? [])
    } catch {
      // optional
    }
  }, [demoMode])

  const loadLogs = useCallback(async () => {
    try {
      if (demoMode) {
        setLogs(mockApi.getLogs().logs)
        return
      }
      const data = await liveApi<{ status: string; logs?: LogEntry[] }>('/api/logs')
      setLogs(data.logs ?? [])
    } catch {
      // optional
    }
  }, [demoMode])

  const refreshAll = useCallback(async () => {
    await loadProperties()
    await loadReservations()
    await loadLogs()
  }, [loadProperties, loadReservations, loadLogs])

  useEffect(() => {
    if (!modeReady) return
    void refreshAll()
  }, [modeReady, refreshAll])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return properties.filter((p) => {
      if (availableOnly && !p.available) return false
      if (minBeds !== '' && (p.beds ?? 0) < Number(minBeds)) return false
      if (!q) return true
      const hay = `${p.name} ${p.city ?? ''} ${p.id}`.toLowerCase()
      return hay.includes(q)
    })
  }, [properties, search, availableOnly, minBeds])

  async function handleBook(e: FormEvent, propertyId: number) {
    e.preventDefault()
    setBookingId(propertyId)
    setResult(null)
    setError(null)
    try {
      const data = demoMode
        ? mockApi.book(propertyId, guestName || 'Guest')
        : await liveApi<BookResult>('/api/reservations', {
            method: 'POST',
            body: JSON.stringify({ property_id: propertyId, guest_name: guestName || 'Guest' }),
          })
      setResult(data)
      setSelected(null)
      await refreshAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Booking failed')
    } finally {
      setBookingId(null)
    }
  }

  async function handleCancel(reservationId: string) {
    setCancellingId(reservationId)
    setResult(null)
    setError(null)
    try {
      const data = demoMode
        ? mockApi.cancel(reservationId)
        : await liveApi<BookResult>('/api/reservations/cancel', {
            method: 'POST',
            body: JSON.stringify({ reservation_id: reservationId }),
          })
      setResult(data)
      await refreshAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cancellation failed')
    } finally {
      setCancellingId(null)
    }
  }

  async function handleHardReset() {
    const first = window.confirm(
      'Reset demo data? This unlocks booked properties and clears reservations.',
    )
    if (!first) return
    const second = window.confirm(
      'Are you sure? This cannot be undone for current demo bookings.',
    )
    if (!second) return

    setResetting(true)
    setResult(null)
    setError(null)
    setSelected(null)
    try {
      const data = demoMode
        ? mockApi.reset()
        : await liveApi<{ status: string; message?: string }>('/api/reset', { method: 'POST' })
      if (data.status !== 'ok') {
        throw new Error(data.message ?? 'Reset failed')
      }
      setResult({ status: 'ok', message: data.message ?? 'Demo data reset' })
      await refreshAll()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
    } finally {
      setResetting(false)
    }
  }

  const activeReservations = reservations.filter((r) => (r.status ?? 'confirmed') !== 'cancelled')
  const cancelledReservations = reservations.filter((r) => r.status === 'cancelled')

  return (
    <div className="app">
      <header className="header">
        <div className="header-text">
          <h1>Distributed Lodging</h1>
          <p className="subtitle">
            CECS 327 Milestone 1 skeleton demo — Property · Reservation · Payment
          </p>
        </div>
        <div className="header-actions">
          <button type="button" className="btn secondary" onClick={() => void refreshAll()}>
            Refresh
          </button>
          <button
            type="button"
            className="btn reset"
            disabled={resetting}
            onClick={() => void handleHardReset()}
          >
            {resetting ? 'Resetting…' : 'Hard reset'}
          </button>
        </div>
      </header>

      {demoMode && (
        <div className="demo-banner" role="status">
          Demo mode (GitHub Pages) — mock data; run local Node services for the real HTTP backend.
        </div>
      )}

      <section className="panel">
        <div className="panel-header">
          <h2>Properties</h2>
          <span className="muted count-label">
            {filtered.length} of {properties.length}
          </span>
        </div>

        <div className="toolbar">
          <label className="guest-label">
            Guest name
            <input
              type="text"
              value={guestName}
              onChange={(e) => setGuestName(e.target.value)}
              placeholder="Your name"
            />
          </label>

          <label className="search-label">
            Search
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Name, city, or ID"
            />
          </label>

          <label className="filter-check">
            <input
              type="checkbox"
              checked={availableOnly}
              onChange={(e) => setAvailableOnly(e.target.checked)}
            />
            Available only
          </label>

          <label className="beds-label">
            Min beds
            <input
              type="number"
              min={0}
              value={minBeds}
              onChange={(e) => setMinBeds(e.target.value)}
              placeholder="Any"
            />
          </label>
        </div>

        {loading && <p className="muted">Loading properties…</p>}
        {error && <p className="error">{error}</p>}

        {!loading && properties.length === 0 && !error && (
          <p className="muted">No properties found. Is the gateway running?</p>
        )}

        {!loading && filtered.length === 0 && properties.length > 0 && (
          <p className="muted">No properties match your search/filters.</p>
        )}

        <div className="card-grid">
          {filtered.map((p) => {
            const hue = CARD_HUES[p.id % CARD_HUES.length]
            return (
              <button
                key={p.id}
                type="button"
                className={`prop-card ${p.available ? 'available' : 'unavailable'}`}
                onClick={() => setSelected(p)}
              >
                <div
                  className="prop-visual"
                  style={{
                    background: `linear-gradient(135deg, hsl(${hue} 45% 72%), hsl(${hue + 30} 40% 55%))`,
                  }}
                  aria-hidden
                >
                  <span className="prop-visual-icon">⌂</span>
                </div>
                <div className="prop-body">
                  <h3>{p.name}</h3>
                  <p className="prop-meta">
                    {p.city ?? '—'} · {p.beds ?? '—'} bed{(p.beds ?? 0) === 1 ? '' : 's'}
                  </p>
                  <div className="prop-footer">
                    <span className="prop-price">${p.price}/night</span>
                    <span className={p.available ? 'badge ok' : 'badge no'}>
                      {p.available ? 'Available' : 'Unavailable'}
                    </span>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Your reservations</h2>
          <button type="button" className="btn secondary" onClick={() => void loadReservations()}>
            Refresh
          </button>
        </div>

        {activeReservations.length === 0 ? (
          <p className="muted">No active reservations. Open a card and book.</p>
        ) : (
          <ul className="reservation-list">
            {activeReservations.map((r) => (
              <li key={r.reservation_id} className="reservation-row">
                <div className="property-info">
                  <h3>{r.property_name ?? `Property ${r.property_id}`}</h3>
                  <p>
                    {r.reservation_id} · {r.guest_name} · ${r.amount}
                    {r.payment_id ? ` · ${r.payment_id}` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  className="btn danger"
                  disabled={cancellingId === r.reservation_id}
                  onClick={() => void handleCancel(r.reservation_id)}
                >
                  {cancellingId === r.reservation_id ? 'Cancelling…' : 'Cancel'}
                </button>
              </li>
            ))}
          </ul>
        )}

        {cancelledReservations.length > 0 && (
          <div className="cancelled-block">
            <h3 className="cancelled-heading">Cancelled</h3>
            <ul className="reservation-list">
              {cancelledReservations.map((r) => (
                <li key={r.reservation_id} className="reservation-row muted-row">
                  <div className="property-info">
                    <h3>{r.property_name ?? `Property ${r.property_id}`}</h3>
                    <p>
                      {r.reservation_id} · {r.guest_name} · refunded
                      {r.refund_id ? ` (${r.refund_id})` : ''}
                    </p>
                  </div>
                  <span className="badge no">Cancelled</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {result && (
        <section className={`panel result ${result.status}`}>
          <h2>Last action</h2>
          <p>
            <strong>Status:</strong> {result.status}
          </p>
          {result.message && (
            <p>
              <strong>Message:</strong> {result.message}
            </p>
          )}
          {result.reservation && (
            <ul className="detail-list">
              <li>Reservation ID: {result.reservation.reservation_id}</li>
              <li>Property: {result.reservation.property_name ?? result.reservation.property_id}</li>
              <li>Guest: {result.reservation.guest_name}</li>
              <li>Amount: ${result.reservation.amount}</li>
              {result.reservation.payment_id && (
                <li>Payment ID: {result.reservation.payment_id}</li>
              )}
              {result.reservation.refund_id && (
                <li>Refund ID: {result.reservation.refund_id}</li>
              )}
            </ul>
          )}
          {result.payment && (
            <p>
              <strong>Payment:</strong> {result.payment.status}
              {result.payment.message ? ` — ${result.payment.message}` : ''}
            </p>
          )}
          {result.refund && (
            <p>
              <strong>Refund:</strong> {result.refund.status}
              {result.refund.message ? ` — ${result.refund.message}` : ''}
            </p>
          )}
        </section>
      )}

      <section className="panel">
        <div className="panel-header">
          <h2>
            <button
              type="button"
              className="collapse-toggle"
              onClick={() => setLogsOpen((o) => !o)}
            >
              Activity log {logsOpen ? '▾' : '▸'}
            </button>
          </h2>
          <button type="button" className="btn secondary" onClick={() => void loadLogs()}>
            Refresh logs
          </button>
        </div>
        {logsOpen &&
          (logs.length === 0 ? (
            <p className="muted">No log lines yet.</p>
          ) : (
            <pre className="log-panel">
              {logs.map((entry, i) => (
                <div key={`${entry.file}-${i}`}>
                  [{entry.file}] {entry.line}
                </div>
              ))}
            </pre>
          ))}
      </section>

      {selected && (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setSelected(null)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setSelected(null)
          }}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="detail-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="modal-visual"
              style={{
                background: `linear-gradient(135deg, hsl(${CARD_HUES[selected.id % CARD_HUES.length]} 45% 72%), hsl(${CARD_HUES[selected.id % CARD_HUES.length] + 30} 40% 55%))`,
              }}
            >
              <span className="prop-visual-icon">⌂</span>
            </div>
            <div className="modal-body">
              <h2 id="detail-title">{selected.name}</h2>
              <ul className="detail-list">
                <li>ID: {selected.id}</li>
                <li>City: {selected.city ?? '—'}</li>
                <li>Beds: {selected.beds ?? '—'}</li>
                <li>Price: ${selected.price}/night</li>
                <li>
                  Status:{' '}
                  <span className={selected.available ? 'badge ok' : 'badge no'}>
                    {selected.available ? 'Available' : 'Unavailable'}
                  </span>
                </li>
              </ul>
              <div className="modal-actions">
                <button type="button" className="btn secondary" onClick={() => setSelected(null)}>
                  Close
                </button>
                {selected.available ? (
                  <form onSubmit={(e) => void handleBook(e, selected.id)}>
                    <button
                      type="submit"
                      className="btn primary"
                      disabled={bookingId === selected.id}
                    >
                      {bookingId === selected.id ? 'Booking…' : `Book as ${guestName || 'Guest'}`}
                    </button>
                  </form>
                ) : (
                  <button type="button" className="btn" disabled>
                    Unavailable
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
