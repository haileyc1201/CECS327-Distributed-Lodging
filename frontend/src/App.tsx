import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'

type Property = {
  id: number
  name: string
  price: number
  available: boolean
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

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
    ...options,
  })
  const data = await res.json()
  return data as T
}

function App() {
  const [properties, setProperties] = useState<Property[]>([])
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [guestName, setGuestName] = useState('Tom')
  const [bookingId, setBookingId] = useState<number | null>(null)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [result, setResult] = useState<BookResult | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])

  const loadProperties = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api<{ status: string; properties?: Property[]; message?: string }>(
        '/api/properties',
      )
      if (data.status !== 'success' || !data.properties) {
        throw new Error(data.message ?? 'Failed to load properties')
      }
      setProperties(data.properties)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load properties')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadReservations = useCallback(async () => {
    try {
      const data = await api<{ status: string; reservations?: Reservation[] }>('/api/reservations')
      setReservations(data.reservations ?? [])
    } catch {
      // optional — ignore if service not ready
    }
  }, [])

  const loadLogs = useCallback(async () => {
    try {
      const data = await api<{ status: string; logs?: LogEntry[] }>('/api/logs')
      setLogs(data.logs ?? [])
    } catch {
      // optional panel — ignore errors
    }
  }, [])

  const refreshAll = useCallback(async () => {
    await loadProperties()
    await loadReservations()
    await loadLogs()
  }, [loadProperties, loadReservations, loadLogs])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  async function handleBook(e: FormEvent, propertyId: number) {
    e.preventDefault()
    setBookingId(propertyId)
    setResult(null)
    setError(null)
    try {
      const data = await api<BookResult>('/api/reservations', {
        method: 'POST',
        body: JSON.stringify({ property_id: propertyId, guest_name: guestName || 'Guest' }),
      })
      setResult(data)
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
      const data = await api<BookResult>('/api/reservations/cancel', {
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

  const activeReservations = reservations.filter((r) => (r.status ?? 'confirmed') !== 'cancelled')
  const cancelledReservations = reservations.filter((r) => r.status === 'cancelled')

  return (
    <div className="app">
      <header className="header">
        <h1>Distributed Lodging</h1>
        <p className="subtitle">CECS 327 Milestone 1 — Property · Reservation · Payment</p>
      </header>

      <section className="panel">
        <div className="panel-header">
          <h2>Properties</h2>
          <button type="button" className="btn secondary" onClick={() => void refreshAll()}>
            Refresh
          </button>
        </div>

        <label className="guest-label">
          Guest name
          <input
            type="text"
            value={guestName}
            onChange={(e) => setGuestName(e.target.value)}
            placeholder="Your name"
          />
        </label>

        {loading && <p className="muted">Loading properties…</p>}
        {error && <p className="error">{error}</p>}

        {!loading && properties.length === 0 && !error && (
          <p className="muted">No properties found. Is the gateway running?</p>
        )}

        <ul className="property-list">
          {properties.map((p) => (
            <li key={p.id} className={`property-card ${p.available ? 'available' : 'unavailable'}`}>
              <div className="property-info">
                <h3>{p.name}</h3>
                <p>
                  ID {p.id} · ${p.price}/night ·{' '}
                  <span className={p.available ? 'badge ok' : 'badge no'}>
                    {p.available ? 'Available' : 'Unavailable'}
                  </span>
                </p>
              </div>
              {p.available ? (
                <form onSubmit={(e) => void handleBook(e, p.id)}>
                  <button type="submit" className="btn primary" disabled={bookingId === p.id}>
                    {bookingId === p.id ? 'Booking…' : 'Book'}
                  </button>
                </form>
              ) : (
                <button type="button" className="btn" disabled>
                  Booked
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Your reservations</h2>
          <button type="button" className="btn secondary" onClick={() => void loadReservations()}>
            Refresh
          </button>
        </div>

        {activeReservations.length === 0 ? (
          <p className="muted">No active reservations. Book a property above.</p>
        ) : (
          <ul className="property-list">
            {activeReservations.map((r) => (
              <li key={r.reservation_id} className="property-card available">
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
            <ul className="property-list">
              {cancelledReservations.map((r) => (
                <li key={r.reservation_id} className="property-card unavailable">
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
          <h2>Activity log</h2>
          <button type="button" className="btn secondary" onClick={() => void loadLogs()}>
            Refresh logs
          </button>
        </div>
        {logs.length === 0 ? (
          <p className="muted">No log lines yet.</p>
        ) : (
          <pre className="log-panel">
            {logs.map((entry, i) => (
              <div key={`${entry.file}-${i}`}>
                [{entry.file}] {entry.line}
              </div>
            ))}
          </pre>
        )}
      </section>
    </div>
  )
}

export default App
