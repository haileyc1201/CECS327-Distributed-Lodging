/**
 * CECS 327 Lodging — Cloudflare Worker (Hono)
 * Serves React assets + /api/* matching the Express gateway contract.
 * Internal modules keep Property / Payment / Reservation separation for the writeup.
 */
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { appendLog, readRecentLogs } from './logger'
import {
  bookReservation,
  cancelReservation,
  listReservations,
  resetDemoData,
} from './services/reservationService'
import { findProperty, listProperties } from './services/propertyService'
import type { Env } from './types'

const app = new Hono<{ Bindings: Env }>()

app.use(
  '/api/*',
  cors({
    origin: '*',
    allowMethods: ['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    allowHeaders: ['Content-Type'],
  }),
)

function gatewayLog(message: string) {
  appendLog('gateway', message)
}

app.get('/api/health', (c) => c.json({ status: 'ok' }))

app.get('/api/properties', async (c) => {
  try {
    const properties = await listProperties(c.env.DB)
    return c.json({ status: 'success', properties })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`properties error: ${message}`)
    return c.json({ status: 'error', message }, 502)
  }
})

app.get('/api/properties/:id', async (c) => {
  try {
    const property = await findProperty(c.env.DB, c.req.param('id'))
    if (!property) {
      return c.json({ status: 'error', message: 'Property not found' }, 404)
    }
    return c.json({ status: 'success', property })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`get property error: ${message}`)
    return c.json({ status: 'error', message }, 502)
  }
})

app.post('/api/reservations', async (c) => {
  try {
    const body = (await c.req.json().catch(() => ({}))) as {
      property_id?: number | string
      guest_name?: string
    }
    if (body.property_id == null) {
      return c.json({ status: 'rejected', message: 'property_id is required' }, 400)
    }
    const { httpStatus, body: data } = await bookReservation(
      c.env.DB,
      body.property_id,
      body.guest_name || 'Guest',
    )
    return c.json(data, httpStatus as 200 | 400 | 502)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`book error: ${message}`)
    return c.json({ status: 'error', message }, 502)
  }
})

app.get('/api/reservations', async (c) => {
  try {
    const reservations = await listReservations(c.env.DB)
    return c.json({ status: 'success', reservations })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`list reservations error: ${message}`)
    return c.json({ status: 'error', message }, 502)
  }
})

app.post('/api/reservations/cancel', async (c) => {
  try {
    const body = (await c.req.json().catch(() => ({}))) as {
      reservation_id?: string
    }
    const { httpStatus, body: data } = await cancelReservation(
      c.env.DB,
      body.reservation_id,
    )
    return c.json(data, httpStatus as 200 | 400 | 502)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`cancel error: ${message}`)
    return c.json({ status: 'error', message }, 502)
  }
})

app.delete('/api/reservations/:id', async (c) => {
  try {
    const { httpStatus, body: data } = await cancelReservation(
      c.env.DB,
      c.req.param('id'),
    )
    return c.json(data, httpStatus as 200 | 400 | 502)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`delete cancel error: ${message}`)
    return c.json({ status: 'error', message }, 502)
  }
})

app.post('/api/reset', async (c) => {
  try {
    await resetDemoData(c.env.DB)
    gatewayLog('Demo data reset')
    return c.json({ status: 'ok', message: 'Demo data reset' })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    gatewayLog(`reset error: ${message}`)
    return c.json({ status: 'error', message }, 500)
  }
})

app.get('/api/logs', (c) => {
  try {
    const logs = readRecentLogs(100)
    return c.json({ status: 'ok', logs })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return c.json({ status: 'error', message }, 500)
  }
})

// Non-API: serve Vite build via Workers Assets (SPA fallback in wrangler.toml)
app.all('*', async (c) => {
  return c.env.ASSETS.fetch(c.req.raw)
})

export default app
