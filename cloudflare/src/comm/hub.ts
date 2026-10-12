/**
 * CommHub Durable Object — one globally unique instance ("global") that acts as
 * the publish-subscribe broker and the group-communication coordinator for the
 * hosted demo. Because a Durable Object is single-threaded and strongly
 * consistent, every node sees the same subscriber list, membership view and
 * sequence numbers.
 *
 * Delivery channels:
 *   - built-in subscribers (notification / analytics / audit services) run here
 *   - WebSocket subscribers / members  (GET /api/comm/ws?role=...)
 *   - mailbox members: HTTP-joined nodes; deliveries are queued and fetched with
 *     group.inbox. They hold a lease renewed by group.heartbeat (failure detection).
 */
import { DurableObject } from 'cloudflare:workers'
import { formatFromContentType, makeEnvelope, marshal, unmarshal, type Envelope } from './marshal'
import { MessageLog } from './msglog'
import type { Env } from '../types'

const NODE = 'comm-hub'
const LEASE_MS = 10 * 60 * 1000
export const BUILTIN_SUBSCRIBERS: Record<string, (e: Record<string, unknown>) => string> = {
  'notification-service': (e) => `send confirmation email to ${e.guest_name} for ${e.property_name}`,
  'analytics-service': (e) => `record revenue $${e.amount} for property ${e.property_id}`,
  'audit-service': (e) => `append audit record for ${e.reservation_id}`,
}

type Member = { mode: 'mailbox' | 'websocket'; joined_at: string; last_seen: number }
type WsTag = { role: 'subscriber' | 'member'; name: string; key: string }

export class CommHub extends DurableObject<Env> {
  private async get<T>(key: string, fallback: T): Promise<T> {
    return ((await this.ctx.storage.get<T>(key)) ?? fallback) as T
  }
  private async next(counter: string): Promise<number> {
    const n = (await this.get<number>(counter, 0)) + 1
    await this.ctx.storage.put(counter, n)
    return n
  }

  // ---------------------------------------------------------------- pub-sub
  private async subscriberNames(topic: string): Promise<string[]> {
    const ws = this.ctx.getWebSockets(`sub:${topic}`).map((s) => (s.deserializeAttachment() as WsTag).name)
    const builtin = topic === 'booking.created' ? Object.keys(BUILTIN_SUBSCRIBERS) : []
    return [...new Set([...builtin, ...ws])].sort()
  }

  private async publish(log: MessageLog, topic: string, event: Record<string, unknown>, publisher: string) {
    const seq = await this.next('seq:event')
    const delivered: string[] = []
    const failed: string[] = []
    if (topic === 'booking.created') {
      for (const [name, action] of Object.entries(BUILTIN_SUBSCRIBERS)) {
        const env = makeEnvelope('event', NODE, { topic, seq, publisher, event }, { receiver: name })
        const wire = marshal(env)
        log.send(NODE, name, env, wire, 'json')
        log.recv(name, NODE, wire, unmarshal(wire), 'json')
        log.info(name, action(event))
        delivered.push(name)
      }
    }
    for (const ws of this.ctx.getWebSockets(`sub:${topic}`)) {
      const tag = ws.deserializeAttachment() as WsTag
      const env = makeEnvelope('event', NODE, { topic, seq, publisher, event }, { receiver: tag.name })
      try {
        const wire = marshal(env)
        ws.send(wire)
        log.send(NODE, `ws:${tag.name}`, env, wire, 'json')
        delivered.push(tag.name)
      } catch {
        failed.push(tag.name)
      }
    }
    return { topic, seq, delivered_to: delivered.sort(), failed: failed.sort() }
  }

  // ---------------------------------------------------------------- group
  private async membersMap(group: string): Promise<Record<string, Member>> {
    return this.get<Record<string, Member>>(`members:${group}`, {})
  }

  private async join(group: string, member: string, mode: Member['mode']) {
    const m = await this.membersMap(group)
    m[member] = { mode, joined_at: new Date().toISOString(), last_seen: Date.now() }
    await this.ctx.storage.put(`members:${group}`, m)
    return { group, members: Object.keys(m).sort() }
  }

  private async leave(log: MessageLog, group: string, member: string) {
    const m = await this.membersMap(group)
    delete m[member]
    await this.ctx.storage.put(`members:${group}`, m)
    await this.ctx.storage.delete(`inbox:${group}:${member}`)
    await this.fanout(log, group, 'group.view', { group, view_id: await this.next('seq:view'), members: Object.keys(m).sort() })
    return { group, members: Object.keys(m).sort() }
  }

  /** Delivers one numbered copy to every current member; expired/closed members are removed. */
  private async fanout(log: MessageLog, group: string, type: string, payload: Record<string, unknown>) {
    const m = await this.membersMap(group)
    const delivered: string[] = []
    const failed: string[] = []
    const sockets = new Map(
      this.ctx.getWebSockets(`member:${group}`).map((s) => [(s.deserializeAttachment() as WsTag).name, s]),
    )
    for (const [name, info] of Object.entries(m).sort()) {
      const env = makeEnvelope(type, NODE, payload, { receiver: name })
      const wire = marshal(env)
      if (info.mode === 'websocket') {
        const ws = sockets.get(name)
        if (!ws) { failed.push(name); continue }
        try {
          ws.send(wire)
          log.send(NODE, `ws:${name}`, env, wire, 'json')
          delivered.push(name)
        } catch {
          failed.push(name)
        }
      } else if (Date.now() - info.last_seen > LEASE_MS) {
        failed.push(name)
      } else {
        const key = `inbox:${group}:${name}`
        const inbox = await this.get<Envelope[]>(key, [])
        inbox.push(env)
        await this.ctx.storage.put(key, inbox.slice(-50))
        log.send(NODE, `mailbox:${name}`, env, wire, 'json')
        delivered.push(name)
      }
    }
    if (failed.length) {
      for (const f of failed) delete m[f]
      await this.ctx.storage.put(`members:${group}`, m)
      log.info(NODE, `removed unreachable members ${JSON.stringify(failed)} from ${group}`)
      if (type !== 'group.view') {
        await this.fanout(log, group, 'group.view', { group, view_id: await this.next('seq:view'), members: Object.keys(m).sort() })
      }
    }
    return { delivered: delivered.sort(), failed: failed.sort() }
  }

  private async multicast(log: MessageLog, group: string, message: unknown, origin: string) {
    const seq = await this.next(`seq:group:${group}`)
    const r = await this.fanout(log, group, 'group.deliver', { group, seq, origin, message })
    return { group, seq, delivered_to: r.delivered, failed: r.failed }
  }

  // ---------------------------------------------------------------- HTTP entry
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url)
    const log = new MessageLog(this.env.DB)
    try {
      if (url.pathname === '/ws') return await this.acceptSocket(url, log)
      const fmt = formatFromContentType(request.headers.get('content-type'))
      const wire = await request.text()
      const env = unmarshal(wire, fmt)
      log.recv(NODE, env.sender, wire, env, fmt)
      const p = (env.payload || {}) as Record<string, any>
      let type = `${env.type}.ack`
      let out: unknown
      switch (env.type) {
        case 'publish': out = await this.publish(log, p.topic, p.event || {}, env.sender); break
        case 'subscribers': out = { topic: p.topic, subscribers: await this.subscriberNames(p.topic) }; type = 'subscribers.reply'; break
        case 'group.join': {
          out = await this.join(p.group, p.member, 'mailbox')
          await this.fanout(log, p.group, 'group.view', { group: p.group, view_id: await this.next('seq:view'), members: (out as any).members })
          break
        }
        case 'group.leave': out = await this.leave(log, p.group, p.member); break
        case 'group.heartbeat': {
          const m = await this.membersMap(p.group)
          if (m[p.member]) { m[p.member].last_seen = Date.now(); await this.ctx.storage.put(`members:${p.group}`, m) }
          out = { group: p.group, member: p.member, alive: !!m[p.member] }
          break
        }
        case 'group.members': {
          const m = await this.membersMap(p.group)
          out = { group: p.group, members: Object.keys(m).sort(), detail: m }
          type = 'group.members.reply'
          break
        }
        case 'group.multicast': out = await this.multicast(log, p.group, p.message, env.sender); break
        case 'group.inbox': {
          const key = `inbox:${p.group}:${p.member}`
          const inbox = await this.get<Envelope[]>(key, [])
          await this.ctx.storage.put(key, [])
          const m = await this.membersMap(p.group)
          if (m[p.member]) { m[p.member].last_seen = Date.now(); await this.ctx.storage.put(`members:${p.group}`, m) }
          for (const msg of inbox) log.recv(p.member, NODE, marshal(msg), msg, 'json')
          out = { group: p.group, member: p.member, messages: inbox }
          type = 'group.inbox.reply'
          break
        }
        default:
          return new Response(JSON.stringify({ error: `unknown message type ${env.type}` }), { status: 400 })
      }
      const reply = makeEnvelope(type, NODE, out, { receiver: env.sender, correlationId: env.id })
      const replyWire = marshal(reply, fmt)
      log.send(NODE, env.sender, reply, replyWire, fmt)
      return new Response(replyWire, { headers: { 'content-type': fmt === 'xml' ? 'application/xml' : 'application/json' } })
    } finally {
      await log.flush()
    }
  }

  private async acceptSocket(url: URL, log: MessageLog): Promise<Response> {
    const role = url.searchParams.get('role') === 'member' ? 'member' : 'subscriber'
    const name = url.searchParams.get('name') || `ws-${crypto.randomUUID().slice(0, 6)}`
    const key = role === 'member' ? url.searchParams.get('group') || 'property-replicas' : url.searchParams.get('topic') || 'booking.created'
    const pair = new WebSocketPair()
    const [client, server] = Object.values(pair)
    this.ctx.acceptWebSocket(server, [`${role === 'member' ? 'member' : 'sub'}:${key}`])
    server.serializeAttachment({ role, name, key } satisfies WsTag)
    log.info(NODE, `websocket ${role} ${name} connected (${key})`)
    if (role === 'member') {
      const view = await this.join(key, name, 'websocket')
      const env = makeEnvelope('group.join.ack', NODE, view, { receiver: name })
      server.send(marshal(env))
      log.send(NODE, `ws:${name}`, env, marshal(env), 'json')
      await this.fanout(log, key, 'group.view', { group: key, view_id: await this.next('seq:view'), members: view.members })
    } else {
      const env = makeEnvelope('subscribe.ack', NODE, { topic: key, subscriber: name }, { receiver: name })
      server.send(marshal(env))
      log.send(NODE, `ws:${name}`, env, marshal(env), 'json')
    }
    return new Response(null, { status: 101, webSocket: client })
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    const log = new MessageLog(this.env.DB)
    const tag = ws.deserializeAttachment() as WsTag
    const text = typeof message === 'string' ? message : new TextDecoder().decode(message)
    try {
      const env = unmarshal(text)
      log.recv(NODE, `ws:${tag.name}`, text, env, 'json')
      if (env.type === 'publish') {
        const p = env.payload as Record<string, any>
        await this.publish(log, p.topic, p.event, env.sender)
      } else if (env.type === 'group.multicast') {
        const p = env.payload as Record<string, any>
        await this.multicast(log, p.group, p.message, env.sender)
      }
    } catch (err) {
      log.info(NODE, `bad websocket message from ${tag.name}: ${err}`)
    }
    await log.flush()
  }

  async webSocketClose(ws: WebSocket) {
    const tag = ws.deserializeAttachment() as WsTag
    const log = new MessageLog(this.env.DB)
    log.info(NODE, `websocket ${tag.role} ${tag.name} closed`)
    if (tag.role === 'member') await this.leave(log, tag.key, tag.name)
    await log.flush()
  }

  async webSocketError(ws: WebSocket) {
    await this.webSocketClose(ws)
  }
}
