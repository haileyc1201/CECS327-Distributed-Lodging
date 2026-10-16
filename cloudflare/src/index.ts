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
import { maskError } from './lib/errors'
import { announceBooking, comm } from './comm/routes'
import { MessageLog } from './comm/msglog'

export { CommHub } from './comm/hub'

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
    return c.json(maskError(gatewayLog, 'properties error', err), 502)
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
    return c.json(maskError(gatewayLog, 'get property error', err), 502)
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
    if (data.status === 'accepted') {
      // communication milestone: booking.created pub-sub + replica multicast
      const log = new MessageLog(c.env.DB)
      Object.assign(data, await announceBooking(c.env, log, data.reservation as Record<string, unknown>))
      c.executionCtx.waitUntil(log.flush())
    }
    return c.json(data, httpStatus as 200 | 400 | 502)
  } catch (err) {
    return c.json(maskError(gatewayLog, 'book error', err), 502)
  }
})

app.get('/api/reservations', async (c) => {
  try {
    const reservations = await listReservations(c.env.DB)
    return c.json({ status: 'success', reservations })
  } catch (err) {
    return c.json(maskError(gatewayLog, 'list reservations error', err), 502)
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
    return c.json(maskError(gatewayLog, 'cancel error', err), 502)
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
    return c.json(maskError(gatewayLog, 'delete cancel error', err), 502)
  }
})

app.post('/api/reset', async (c) => {
  try {
    await resetDemoData(c.env.DB)
    gatewayLog('Demo data reset')
    return c.json({ status: 'ok', message: 'Demo data reset' })
  } catch (err) {
    return c.json(maskError(gatewayLog, 'reset error', err), 500)
  }
})

app.get('/api/logs', (c) => {
  try {
    const logs = readRecentLogs(100)
    return c.json({ status: 'ok', logs })
  } catch (err) {
    return c.json(maskError(gatewayLog, 'logs error', err), 500)
  }
})

// Communication milestone routes (RPC, pub-sub, group, WebSocket, message log)
app.route('/api', comm)

// Path aliases: /lodging → same app (API + UI)
app.get('/lodging', (c) => c.redirect('/', 302))
app.get('/lodging/', (c) => c.redirect('/', 302))
app.all('/lodging/*', (c) => {
  const url = new URL(c.req.url)
  url.pathname = url.pathname.replace(/^\/lodging/, '') || '/'
  return app.fetch(new Request(url.toString(), c.req.raw), c.env, c.executionCtx)
})

// Non-API: serve Vite build via Workers Assets (SPA fallback in wrangler.toml)
app.all('*', async (c) => {
  return c.env.ASSETS.fetch(c.req.raw)
})

export default app
