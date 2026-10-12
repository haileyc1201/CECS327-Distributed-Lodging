/**
 * Communication Hub — Express HTTP on :5010
 *
 *  POST /rpc        JSON-RPC 2.0 (request-reply). Body = envelope whose payload is a
 *                   JSON-RPC request; JSON or XML (Content-Type decides).
 *  POST /publish    publish-subscribe: envelope {topic, event} fanned out to every
 *                   subscriber of the topic (HTTP push to each subscriber's /deliver)
 *  POST /subscribe  envelope {topic, name, url}  register a subscriber
 *  POST /group/join | /group/leave | /group/multicast   group communication
 *  GET  /group/members?group=   GET /subscribers   GET /logs?limit=   GET /health
 */
const express = require('express');
const cors = require('cors');
const {
  makeEnvelope, makeLogger, sendMessage, envelopeBody, replyEnvelope, readMessageLog,
} = require('../shared/messaging');

const HOST = process.env.HUB_HOST || '127.0.0.1';
const PORT = Number(process.env.HUB_PORT || 5010);
const PROPERTY_URL = process.env.PROPERTY_URL || 'http://127.0.0.1:5001';
const RESERVATION_URL = process.env.RESERVATION_URL || 'http://127.0.0.1:5002';
const NAME = 'comm-hub';
const logger = makeLogger(NAME);

const subscribers = new Map(); // topic -> Map(name -> url)
const groups = new Map(); // group -> Map(member -> {url, joined_at})
let eventSeq = 0;
let groupSeq = 0;
let viewId = 0;

// ------------------------------------------------------------- pub-sub
async function publish(topic, event, publisher) {
  const seq = ++eventSeq;
  const targets = [...(subscribers.get(topic) || new Map()).entries()];
  const delivered = [];
  const failed = [];
  await Promise.all(targets.map(async ([name, url]) => {
    const env = makeEnvelope('event', NAME, { topic, seq, publisher, event }, { receiver: name });
    try {
      const ack = await sendMessage(logger, url, env);
      (ack.type === 'event.ack' ? delivered : failed).push(name);
    } catch {
      failed.push(name);
    }
  }));
  for (const name of failed) subscribers.get(topic)?.delete(name);
  return { topic, seq, delivered_to: delivered.sort(), failed: failed.sort() };
}

// ------------------------------------------------------------- group communication
const members = (group) => [...(groups.get(group) || new Map()).keys()].sort();

async function fanout(group, type, payload) {
  const targets = [...(groups.get(group) || new Map()).entries()];
  const delivered = [];
  const failed = [];
  await Promise.all(targets.map(async ([member, info]) => {
    const env = makeEnvelope(type, NAME, payload, { receiver: member });
    try {
      const ack = await sendMessage(logger, info.url, env);
      (ack.type === 'group.ack' ? delivered : failed).push(member);
    } catch {
      failed.push(member);
    }
  }));
  if (failed.length) {
    for (const m of failed) groups.get(group)?.delete(m);
    logger.info(`removed unreachable members ${JSON.stringify(failed)} from ${group}`);
    await announceView(group);
  }
  return { delivered: delivered.sort(), failed: failed.sort() };
}

async function announceView(group) {
  await fanout(group, 'group.view', { group, view_id: ++viewId, members: members(group) });
}

async function multicast(group, message, origin) {
  const seq = ++groupSeq;
  const r = await fanout(group, 'group.deliver', { group, seq, origin, message });
  return { group, seq, delivered_to: r.delivered, failed: r.failed };
}

function join(group, member, url) {
  if (!groups.has(group)) groups.set(group, new Map());
  groups.get(group).set(member, { url, joined_at: new Date().toISOString() });
  setImmediate(() => announceView(group).catch(() => {}));
  return { group, members: members(group) };
}

function leave(group, member) {
  groups.get(group)?.delete(member);
  setImmediate(() => announceView(group).catch(() => {}));
  return { group, members: members(group) };
}

// ------------------------------------------------------------- JSON-RPC
async function http(url, opts = {}) {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
  return r.json();
}

class RpcError extends Error {
  constructor(code, message, data) { super(message); this.code = code; this.data = data; }
}

const methods = {
  'rpc.ping': () => 'pong',
  'rpc.methods': () => Object.keys(methods).sort(),
  'property.list': async () => (await http(`${PROPERTY_URL}/properties`)).properties,
  'property.get': async ({ property_id }) => {
    const r = await http(`${PROPERTY_URL}/properties/${property_id}`);
    if (r.status !== 'success') throw new RpcError(404, 'Property not found', { property_id });
    return r.property;
  },
  'availability.check': async ({ property_id }) => {
    const p = await methods['property.get']({ property_id });
    return { property_id: p.id, name: p.name, available: p.available, price: p.price };
  },
  'reservation.book': async ({ property_id, guest_name = 'Guest' }) =>
    http(`${RESERVATION_URL}/reservations`, { method: 'POST', body: JSON.stringify({ property_id, guest_name }) }),
  'reservation.list': async () => (await http(`${RESERVATION_URL}/reservations`)).reservations,
  'pubsub.publish': ({ topic, event }, sender) => publish(topic, event, sender),
  'pubsub.subscribers': ({ topic }) => [...(subscribers.get(topic) || new Map()).keys()].sort(),
  'group.join': ({ group, member, url }) => join(group, member, url),
  'group.leave': ({ group, member }) => leave(group, member),
  'group.members': ({ group }) => ({ group, members: members(group) }),
  'group.multicast': ({ group, message }, sender) => multicast(group, message, sender),
};

// ------------------------------------------------------------- HTTP
const app = express();
app.use(cors());
const body = envelopeBody(logger);

const reply = (req, res, type, payload, status = 200) =>
  replyEnvelope(logger, req, res, makeEnvelope(type, NAME, payload, {
    receiver: req.envelope?.sender || null, correlationId: req.envelope?.id || null,
  }), status);

app.get('/health', (_req, res) => res.json({ status: 'ok', service: NAME }));

app.post('/rpc', body, async (req, res) => {
  const rpc = req.envelope.payload || {};
  const fn = methods[rpc.method];
  let out;
  if (req.envelope.type !== 'rpc.request' || rpc.jsonrpc !== '2.0') {
    out = { jsonrpc: '2.0', id: rpc.id ?? null, error: { code: -32600, message: 'Invalid Request' } };
  } else if (!fn) {
    out = { jsonrpc: '2.0', id: rpc.id, error: { code: -32601, message: `Method not found: ${rpc.method}` } };
  } else {
    try {
      out = { jsonrpc: '2.0', id: rpc.id, result: await fn(rpc.params || {}, req.envelope.sender) };
    } catch (err) {
      out = { jsonrpc: '2.0', id: rpc.id, error: { code: err.code || -32000, message: err.message, data: err.data } };
    }
  }
  reply(req, res, 'rpc.reply', out);
});

app.post('/publish', body, async (req, res) => {
  const { topic, event } = req.envelope.payload || {};
  reply(req, res, 'publish.ack', await publish(topic, event, req.envelope.sender));
});

app.post('/subscribe', body, (req, res) => {
  const { topic, name, url } = req.envelope.payload || {};
  if (!subscribers.has(topic)) subscribers.set(topic, new Map());
  subscribers.get(topic).set(name, url);
  reply(req, res, 'subscribe.ack', { topic, subscriber: name, subscribers: [...subscribers.get(topic).keys()].sort() });
});

app.post('/group/join', body, (req, res) => {
  const { group, member, url } = req.envelope.payload;
  reply(req, res, 'group.join.ack', join(group, member, url));
});
app.post('/group/leave', body, (req, res) => {
  const { group, member } = req.envelope.payload;
  reply(req, res, 'group.leave.ack', leave(group, member));
});
app.post('/group/multicast', body, async (req, res) => {
  const { group, message } = req.envelope.payload;
  reply(req, res, 'group.multicast.ack', await multicast(group, message, req.envelope.sender));
});
app.get('/group/members', (req, res) => res.json({ group: req.query.group, members: members(req.query.group) }));
app.get('/subscribers', (_req, res) =>
  res.json(Object.fromEntries([...subscribers].map(([t, m]) => [t, [...m.keys()].sort()]))));
app.get('/logs', (req, res) => res.json({ status: 'ok', logs: readMessageLog(Number(req.query.limit) || 200) }));

app.listen(PORT, HOST, () => logger.info(`listening on http://${HOST}:${PORT}`));
