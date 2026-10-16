/**
 * Communication-milestone routes for the hosted Worker.
 *
 *   POST /api/rpc                 JSON-RPC 2.0 (envelope payload; JSON or XML body)
 *   POST /api/publish             publish {topic, event}
 *   GET  /api/subscribers?topic=
 *   POST /api/group/join | /api/group/leave | /api/group/heartbeat | /api/group/multicast
 *   GET  /api/group/members?group=   GET /api/group/inbox?group=&member=
 *   GET  /api/comm/ws?role=subscriber&topic=booking.created&name=x   (WebSocket)
 *   GET  /api/comm/ws?role=member&group=property-replicas&name=x     (WebSocket)
 *   GET  /api/comm/logs?limit=&node=   message log from D1
 */
import { Hono } from 'hono'
import { CONTENT_TYPES, formatFromContentType, makeEnvelope, marshal, unmarshal, type Envelope, type WireFormat } from './marshal'
import { MessageLog, readMessageLog } from './msglog'
import { findProperty, listProperties } from '../services/propertyService'
import { bookReservation, listReservations } from '../services/reservationService'
import type { Env } from '../types'
import { rpcError } from '../lib/errors'

export const GATEWAY = 'worker-gateway'
export const REPLICA_GROUP = 'property-replicas'

/** Request-reply to the CommHub Durable Object with a marshalled envelope. */
export async function hubCall(env: Env, log: MessageLog, type: string, payload: unknown, sender = GATEWAY,
  fmt: WireFormat = 'json'): Promise<Envelope> {
  const stub = env.COMM_HUB.get(env.COMM_HUB.idFromName('global'))
  const msg = makeEnvelope(type, sender, payload, { receiver: 'comm-hub' })
  const wire = marshal(msg, fmt)
  log.send(GATEWAY, 'comm-hub', msg, wire, fmt)
  const res = await stub.fetch('https://comm-hub/msg', { method: 'POST', headers: { 'content-type': CONTENT_TYPES[fmt] }, body: wire })
  const text = await res.text()
  const rfmt = formatFromContentType(res.headers.get('content-type'))
  const reply = unmarshal(text, rfmt)
  log.recv(GATEWAY, 'comm-hub', text, reply, rfmt)
  return reply
}

/** Called after a successful booking: pub-sub + group multicast. */
export async function announceBooking(env: Env, log: MessageLog, reservation: Record<string, unknown>) {
  const pub = await hubCall(env, log, 'publish', { topic: 'booking.created', event: reservation })
  const mc = await hubCall(env, log, 'group.multicast', {
    group: REPLICA_GROUP,
    message: { op: 'availability_update', property_id: reservation.property_id, available: false, reservation_id: reservation.reservation_id },
  })
  return {
    notified_subscribers: (pub.payload as any).delivered_to as string[],
    replicas_updated: (mc.payload as any).delivered_to as string[],
  }
}

class RpcError extends Error {
  constructor(public code: number, message: string, public data?: unknown) { super(message); this.name = 'RpcError' }
}

type Method = (p: Record<string, any>, env: Env, log: MessageLog, sender: string) => Promise<unknown> | unknown

const hub = async (env: Env, log: MessageLog, type: string, p: unknown, sender: string) =>
  (await hubCall(env, log, type, p, sender)).payload

const methods: Record<string, Method> = {
  'rpc.ping': () => 'pong',
  'rpc.methods': () => Object.keys(methods).sort(),
  'property.list': (_p, env) => listProperties(env.DB),
  'property.get': async (p, env) => {
    const prop = await findProperty(env.DB, p.property_id)
    if (!prop) throw new RpcError(404, 'Property not found', { property_id: p.property_id })
    return prop
  },
  'availability.check': async (p, env, log, s) => {
    const prop = (await methods['property.get'](p, env, log, s)) as any
    return { property_id: prop.id, name: prop.name, available: prop.available, price: prop.price }
  },
  'reservation.list': (_p, env) => listReservations(env.DB),
  'reservation.book': async (p, env, log) => {
    const { body } = await bookReservation(env.DB, p.property_id, p.guest_name || 'Guest')
    if (body.status === 'accepted') Object.assign(body, await announceBooking(env, log, body.reservation as any))
    return body
  },
  'pubsub.publish': (p, env, log, s) => hub(env, log, 'publish', p, s),
  'pubsub.subscribers': (p, env, log, s) => hub(env, log, 'subscribers', p, s),
  'group.join': (p, env, log, s) => hub(env, log, 'group.join', p, s),
  'group.leave': (p, env, log, s) => hub(env, log, 'group.leave', p, s),
  'group.heartbeat': (p, env, log, s) => hub(env, log, 'group.heartbeat', p, s),
  'group.members': (p, env, log, s) => hub(env, log, 'group.members', p, s),
  'group.multicast': (p, env, log, s) => hub(env, log, 'group.multicast', p, s),
  'group.inbox': (p, env, log, s) => hub(env, log, 'group.inbox', p, s),
  'logs.recent': (p, env) => readMessageLog(env.DB, Math.min(Number(p.limit) || 50, 1000), p.node),
}

export const comm = new Hono<{ Bindings: Env }>()

comm.post('/rpc', async (c) => {
  const log = new MessageLog(c.env.DB)
  const fmt = formatFromContentType(c.req.header('content-type'))
  const wire = await c.req.text()
  let env: Envelope
  try {
    env = unmarshal(wire, fmt)
  } catch (err) {
    return c.json({ jsonrpc: '2.0', id: null, error: { code: -32700, message: "Parse error: message is not valid JSON or XML" } }, 400)
  }
  const peer = c.req.header('cf-connecting-ip') || 'client'
  log.recv(GATEWAY, peer, wire, env, fmt)
  const rpc = (env.payload || {}) as Record<string, any>
  let out: Record<string, unknown>
  const fn = methods[rpc.method]
  if (env.type !== 'rpc.request' || rpc.jsonrpc !== '2.0') {
    out = { jsonrpc: '2.0', id: rpc.id ?? null, error: { code: -32600, message: 'Invalid Request' } }
  } else if (!fn) {
    out = { jsonrpc: '2.0', id: rpc.id, error: { code: -32601, message: `Method not found: ${rpc.method}` } }
  } else {
    try {
      out = { jsonrpc: '2.0', id: rpc.id, result: await fn(rpc.params || {}, c.env, log, env.sender) }
    } catch (err) {
      out = { jsonrpc: '2.0', id: rpc.id, error: rpcError((m) => log.info(GATEWAY, m), `rpc ${rpc.method}`, err) }
    }
  }
  const reply = makeEnvelope('rpc.reply', GATEWAY, out, { receiver: env.sender, correlationId: env.id })
  const replyWire = marshal(reply, fmt)
  log.send(GATEWAY, peer, reply, replyWire, fmt)
  c.executionCtx.waitUntil(log.flush())
  return c.body(replyWire, 200, { 'content-type': CONTENT_TYPES[fmt] })
})

/** Plain-JSON convenience endpoints (wrap the body in an envelope for the hub). */
const simple = (type: string, from: 'body' | 'query') => async (c: any) => {
  const log = new MessageLog(c.env.DB)
  const p = from === 'body' ? await c.req.json().catch(() => ({})) : c.req.query()
  const reply = await hubCall(c.env, log, type, p, p.sender || p.member || 'http-client')
  c.executionCtx.waitUntil(log.flush())
  return c.json(reply.payload as Record<string, unknown>)
}
comm.post('/publish', simple('publish', 'body'))
comm.get('/subscribers', simple('subscribers', 'query'))
comm.post('/group/join', simple('group.join', 'body'))
comm.post('/group/leave', simple('group.leave', 'body'))
comm.post('/group/heartbeat', simple('group.heartbeat', 'body'))
comm.post('/group/multicast', simple('group.multicast', 'body'))
comm.get('/group/members', simple('group.members', 'query'))
comm.get('/group/inbox', simple('group.inbox', 'query'))

comm.get('/comm/ws', (c) => {
  if (c.req.header('upgrade')?.toLowerCase() !== 'websocket') return c.text('Expected WebSocket upgrade', 426)
  const stub = c.env.COMM_HUB.get(c.env.COMM_HUB.idFromName('global'))
  const url = new URL(c.req.url)
  url.pathname = '/ws'
  return stub.fetch(new Request(url.toString(), c.req.raw))
})

comm.get('/comm/logs', async (c) => {
  const limit = Math.min(Number(c.req.query('limit')) || 200, 2000)
  return c.json({ status: 'ok', logs: await readMessageLog(c.env.DB, limit, c.req.query('node') || undefined) })
})
