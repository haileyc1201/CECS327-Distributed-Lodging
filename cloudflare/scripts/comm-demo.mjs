/**
 * Hosted (Cloudflare Worker) communication demo + verification.
 *   BASE_URL=https://<your-worker>.workers.dev node scripts/comm-demo.mjs
 *   BASE_URL=http://127.0.0.1:8787 node scripts/comm-demo.mjs   (wrangler dev)
 * Requires Node 22+ (global WebSocket). Exits non-zero if a check fails.
 */
const BASE = (process.env.BASE_URL || 'http://127.0.0.1:8787').replace(/\/$/, '')
const RUN = Math.random().toString(16).slice(2, 6)
const iso = () => new Date().toISOString()
let failures = 0
const check = (label, cond) => { console.log(`  [${cond ? 'PASS' : 'FAIL'}] ${label}`); if (!cond) failures++ }
const banner = (t) => console.log(`\n=== ${t} ${'='.repeat(Math.max(0, 60 - t.length))}`)
const env = (type, sender, payload) => ({ id: crypto.randomUUID().slice(0, 12), type, sender, receiver: 'worker-gateway', timestamp: iso(), correlation_id: null, payload })

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const toXml = (tag, v) => v === null || v === undefined ? `<${tag} t="null"/>`
  : typeof v === 'boolean' ? `<${tag} t="bool">${v}</${tag}>`
  : typeof v === 'number' ? `<${tag} t="${Number.isInteger(v) ? 'int' : 'float'}">${v}</${tag}>`
  : typeof v === 'string' ? `<${tag} t="str">${esc(v)}</${tag}>`
  : Array.isArray(v) ? `<${tag} t="list">${v.map((x) => toXml('item', x)).join('')}</${tag}>`
  : `<${tag} t="dict">${Object.entries(v).map(([k, x]) => `<entry key="${esc(k)}">${toXml('value', x)}</entry>`).join('')}</${tag}>`

async function rpc(method, params = {}, fmt = 'json') {
  const e = env('rpc.request', `demo-client-${RUN}`, { jsonrpc: '2.0', method, params, id: Date.now() })
  const body = fmt === 'xml' ? `<message>${toXml('envelope', e)}</message>` : JSON.stringify(e)
  const r = await fetch(`${BASE}/api/rpc`, { method: 'POST', headers: { 'content-type': fmt === 'xml' ? 'application/xml' : 'application/json' }, body })
  const text = await r.text()
  if (fmt === 'xml') return { xml: text }
  const reply = JSON.parse(text)
  if (reply.correlation_id !== e.id) throw new Error('correlation id mismatch')
  return reply.payload
}

function openWs(params) {
  const u = new URL(`${BASE.replace(/^http/, 'ws')}/api/comm/ws`)
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v)
  const ws = new WebSocket(u)
  const msgs = []
  ws.addEventListener('message', (m) => msgs.push(JSON.parse(m.data)))
  return new Promise((resolve, reject) => {
    ws.addEventListener('open', () => setTimeout(() => resolve({ ws, msgs }), 300))
    ws.addEventListener('error', reject)
  })
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

banner(`target ${BASE}`)
check('GET /api/health', (await (await fetch(`${BASE}/api/health`)).json()).status === 'ok')
await fetch(`${BASE}/api/reset`, { method: 'POST' })

banner('1. request-reply over HTTP JSON-RPC')
const a = await rpc('availability.check', { property_id: 101 })
console.log('  101 ->', JSON.stringify(a.result)); check('101 available', a.result?.available === true)
const b = await rpc('availability.check', { property_id: 102 })
console.log('  102 ->', JSON.stringify(b.result)); check('102 unavailable', b.result?.available === false)
const x = await rpc('availability.check', { property_id: 103 }, 'xml')
console.log('  103 XML reply ->', x.xml.slice(0, 140) + '...'); check('XML reply is XML envelope', x.xml.startsWith('<message><envelope t="dict">') && x.xml.includes('Beach House'))
check('404 error object', (await rpc('property.get', { property_id: 999 })).error?.code === 404)
check('unknown method -32601', (await rpc('nope')).error?.code === -32601)

banner('2. group membership')
const replicas = [`replica-a-${RUN}`, `replica-b-${RUN}`]
for (const m of replicas) await rpc('group.join', { group: 'property-replicas', member: m })
const wsMember = await openWs({ role: 'member', group: 'property-replicas', name: `replica-ws-${RUN}` })
const wsSub1 = await openWs({ role: 'subscriber', topic: 'booking.created', name: `ws-subscriber-1-${RUN}` })
const wsSub2 = await openWs({ role: 'subscriber', topic: 'booking.created', name: `ws-subscriber-2-${RUN}` })
const mem = (await rpc('group.members', { group: 'property-replicas' })).result
console.log('  members:', mem.members)
check('3 replicas joined (2 mailbox + 1 websocket)', [...replicas, `replica-ws-${RUN}`].every((m) => mem.members.includes(m)))
const subs = (await rpc('pubsub.subscribers', { topic: 'booking.created' })).result
console.log('  booking.created subscribers:', subs.subscribers)
check('>= 5 subscribers (3 built-in + 2 websocket)', subs.subscribers.length >= 5)

banner('3. booking -> pub-sub + multicast')
const book = (await rpc('reservation.book', { property_id: 101, guest_name: `Demo ${RUN}` })).result
console.log('  status', book.status, book.reservation?.reservation_id)
console.log('  notified_subscribers', book.notified_subscribers)
console.log('  replicas_updated', book.replicas_updated)
check('booking accepted', book.status === 'accepted')
check('built-in + websocket subscribers notified', ['notification-service', 'analytics-service', 'audit-service', `ws-subscriber-1-${RUN}`, `ws-subscriber-2-${RUN}`].every((s) => book.notified_subscribers?.includes(s)))
check('all 3 replicas got multicast', [...replicas, `replica-ws-${RUN}`].every((s) => book.replicas_updated?.includes(s)))
await sleep(500)
check('ws subscriber 1 received event', wsSub1.msgs.some((m) => m.type === 'event' && m.payload.event.reservation_id === book.reservation.reservation_id))
check('ws subscriber 2 received event', wsSub2.msgs.some((m) => m.type === 'event' && m.payload.event.reservation_id === book.reservation.reservation_id))
check('ws replica received group.deliver', wsMember.msgs.some((m) => m.type === 'group.deliver' && m.payload.message.property_id === 101))
const inbox = (await rpc('group.inbox', { group: 'property-replicas', member: replicas[0] })).result
check('mailbox replica inbox has the update', inbox.messages.some((m) => m.type === 'group.deliver' && m.payload.message.property_id === 101))
check('double booking rejected', (await rpc('reservation.book', { property_id: 101 })).result.status === 'rejected')

banner('4. failure / leave: websocket replica disconnects')
wsMember.ws.close(); await sleep(800)
const after = (await rpc('group.members', { group: 'property-replicas' })).result.members
console.log('  members now:', after)
check('closed websocket member removed from view', !after.includes(`replica-ws-${RUN}`))
for (const m of replicas) await rpc('group.leave', { group: 'property-replicas', member: m })
wsSub1.ws.close(); wsSub2.ws.close()

banner('5. message log (GET /api/comm/logs)')
await sleep(800)
const logs = (await (await fetch(`${BASE}/api/comm/logs?limit=400`)).json()).logs
const mine = logs.filter((l) => JSON.stringify(l).includes(RUN))
console.log(`  ${logs.length} recent entries, ${mine.length} from this run`)
for (const l of mine.slice(0, 8)) console.log(`  ${l.ts} [${l.node}] ${l.event} ${l.peer || ''} ${l.message?.type || l.note || ''}`)
check('every entry has ISO-8601 ts', logs.every((l) => /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(l.ts)))
check('log has SEND and RECV for this run', mine.some((l) => l.event === 'SEND') && mine.some((l) => l.event === 'RECV'))
await fetch(`${BASE}/api/reset`, { method: 'POST' })
console.log(`\n${failures ? `${failures} check(s) FAILED` : 'ALL CHECKS PASSED'}`)
process.exit(failures ? 1 : 0)
