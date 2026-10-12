/**
 * Communication milestone tests (Node stack).   npm test   (node --test tests/)
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const os = require('os');
const path = require('path');
const fs = require('fs');

process.env.COMM_QUIET = '1';
process.env.COMM_LOG_FILE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'comm-')), 'messages.jsonl');
const { makeEnvelope, makeLogger, sendMessage, marshal, unmarshal, readMessageLog } = require('../services/shared/messaging');
const { resetDemoData } = require('../services/shared/csv');
const { startCluster } = require('../scripts/comm-cluster');

const ISO = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/;

test('TC1 marshalling: JSON and XML round-trip keep types', () => {
  const env = makeEnvelope('event', 't', { n: 3, f: 1.5, ok: false, none: null, l: [1, '2', { x: '<&>' }] });
  assert.match(env.timestamp, ISO);
  for (const fmt of ['json', 'xml']) assert.deepEqual(unmarshal(marshal(env, fmt), fmt), env);
  assert.ok(marshal(env, 'xml').startsWith('<message><envelope t="dict">'));
});

test('cluster', async (t) => {
  resetDemoData();
  const c = await startCluster({ base: 15000 });
  const log = makeLogger('test');
  const rpc = async (method, params, fmt = 'json') => (await sendMessage(log, `${c.urls.gateway}/api/rpc`,
    makeEnvelope('rpc.request', 'test', { jsonrpc: '2.0', method, params, id: 1 }), fmt)).payload;
  t.after(async () => { await c.stop(); resetDemoData(); });

  await t.test('TC2 request-reply: availability.check over JSON-RPC (JSON + XML)', async () => {
    assert.equal((await rpc('availability.check', { property_id: 101 })).result.available, true);
    assert.equal((await rpc('availability.check', { property_id: 102 })).result.available, false);
    assert.equal((await rpc('property.get', { property_id: 103 }, 'xml')).result.name, 'Beach House');
    assert.equal((await rpc('availability.check', { property_id: 999 })).error.code, 404);
    assert.equal((await rpc('nope', {})).error.code, -32601);
  });

  await t.test('TC3 booking publishes to 3 subscribers and multicasts to 3 replicas', async () => {
    const r = (await rpc('reservation.book', { property_id: 101, guest_name: 'Test' })).result;
    assert.equal(r.status, 'accepted');
    assert.deepEqual(r.notified_subscribers, ['analytics-service', 'audit-service', 'notification-service']);
    assert.deepEqual(r.replicas_updated, ['replica-1', 'replica-2', 'replica-3']);
    for (const n of [...c.subs, ...c.replicas]) {
      const s = await (await fetch(`${c.nodeUrl(n)}/state`)).json();
      assert.equal(s.received.length, 1, n);
    }
    assert.equal((await rpc('reservation.book', { property_id: 101 })).result.status, 'rejected');
  });

  await t.test('TC4 group membership: failure removes member, leave updates view', async () => {
    await c.kill('replica-3', 'SIGKILL');
    const ack = (await rpc('group.multicast', { group: 'property-replicas', message: { ping: 1 } })).result;
    assert.deepEqual(ack.failed, ['replica-3']);
    assert.deepEqual((await rpc('group.members', { group: 'property-replicas' })).result.members, ['replica-1', 'replica-2']);
    await c.kill('replica-2', 'SIGINT'); // graceful leave
    assert.deepEqual((await rpc('group.members', { group: 'property-replicas' })).result.members, ['replica-1']);
  });

  await t.test('TC5 pub-sub only delivers to matching topic', async () => {
    const r = (await rpc('pubsub.publish', { topic: 'other.topic', event: { x: 1 } })).result;
    assert.deepEqual(r.delivered_to, []);
  });

  await t.test('TC6 every message logged with ISO-8601 timestamp; /api/comm/logs serves them', async () => {
    const { logs } = await (await fetch(`${c.urls.gateway}/api/comm/logs?limit=5000`)).json();
    assert.ok(logs.length > 20);
    for (const e of logs) assert.match(e.ts, ISO);
    assert.ok(logs.some((e) => e.event === 'SEND' && e.node === 'comm-hub' && e.message.type === 'event'));
    assert.ok(logs.filter((e) => e.event === 'SEND').every((e) => e.message && typeof e.wire === 'string'));
    assert.equal(readMessageLog(5000).length >= logs.length, true);
  });
});
