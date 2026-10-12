/**
 * Communication milestone demo (Node stack).
 *   node scripts/comm-demo.js        (or: npm run comm:demo)
 * Starts property, payment, reservation, gateway, comm-hub, 3 subscribers and
 * 3 group members as separate processes, then exercises every requirement.
 * Message log: logs/messages.jsonl   (also served at GET /api/comm/logs)
 */
const fs = require('fs');
const { startCluster } = require('./comm-cluster');
const { makeEnvelope, makeLogger, sendMessage, marshal, unmarshal, LOG_FILE } = require('../services/shared/messaging');
const { resetDemoData } = require('../services/shared/csv');

const banner = (t) => console.log(`\n=== ${t} ${'='.repeat(Math.max(0, 60 - t.length))}`);
const show = (label, v) => console.log(`  ${label}`, typeof v === 'string' ? v : JSON.stringify(v, null, 2).replace(/\n/g, '\n  '));

(async () => {
  if (!process.argv.includes('--keep-log') && fs.existsSync(LOG_FILE)) fs.unlinkSync(LOG_FILE);
  resetDemoData();
  const c = await startCluster();
  const log = makeLogger('client');
  const rpc = async (method, params, fmt = 'json') => {
    const env = makeEnvelope('rpc.request', 'client', { jsonrpc: '2.0', method, params, id: Date.now() });
    return (await sendMessage(log, `${c.urls.gateway}/api/rpc`, env, fmt)).payload;
  };
  try {
    banner('processes');
    for (const [n, p] of Object.entries(c.procs)) console.log(`  ${n.padEnd(22)} pid=${p.pid}`);

    banner('marshalling round-trip');
    const sample = makeEnvelope('rpc.request', 'client', { jsonrpc: '2.0', method: 'availability.check', params: { property_id: 101 }, id: 1 });
    for (const fmt of ['json', 'xml']) {
      const wire = marshal(sample, fmt);
      const back = unmarshal(wire, fmt);
      console.log(`  ${fmt}: ${Buffer.byteLength(wire)} bytes, round-trip equal = ${JSON.stringify(back) === JSON.stringify(sample)}`);
      console.log(`    ${wire.slice(0, 160)}...`);
      log.info(`marshal round-trip ${fmt}`, { before: sample, after: wire });
    }

    banner('1. request-reply: JSON-RPC availability.check');
    show('101 ->', (await rpc('availability.check', { property_id: 101 })).result);
    show('102 ->', (await rpc('availability.check', { property_id: 102 })).result);
    show('103 (XML on the wire) ->', (await rpc('availability.check', { property_id: 103 }, 'xml')).result);
    show('999 ->', (await rpc('availability.check', { property_id: 999 })).error);
    show('group members:', (await rpc('group.members', { group: 'property-replicas' })).result.members);

    banner('2+3+4. reservation.book -> payment, pub-sub, multicast');
    const ok = (await rpc('reservation.book', { property_id: 101, guest_name: 'Demo Guest' })).result;
    show('booking 101:', { status: ok.status, reservation_id: ok.reservation?.reservation_id, amount: ok.reservation?.amount,
      notified_subscribers: ok.notified_subscribers, replicas_updated: ok.replicas_updated });
    show('booking 101 again:', (await rpc('reservation.book', { property_id: 101 })).result);

    banner('4b. failure: kill replica-3, multicast again');
    await c.kill('replica-3', 'SIGKILL');
    show('multicast ack:', (await rpc('group.multicast', { group: 'property-replicas', message: { op: 'availability_update', property_id: 103, available: true } })).result);
    show('group members now:', (await rpc('group.members', { group: 'property-replicas' })).result.members);
    await new Promise((r) => setTimeout(r, 300));

    banner('subscriber / replica state');
    for (const n of ['notification-service', 'analytics-service', 'audit-service', 'replica-1', 'replica-2']) {
      const s = await (await fetch(`${c.nodeUrl(n)}/state`)).json();
      console.log(`  ${n.padEnd(22)} received=${s.received.length} cache=${JSON.stringify(s.cache)} view=${JSON.stringify(s.view)}`);
    }
    const logs = await (await fetch(`${c.urls.gateway}/api/comm/logs?limit=1000`)).json();
    const sends = logs.logs.filter((e) => e.event === 'SEND').length;
    const recvs = logs.logs.filter((e) => e.event === 'RECV').length;
    console.log(`\n  GET /api/comm/logs -> ${logs.logs.length} entries (${sends} SEND, ${recvs} RECV)`);
    console.log(`  Full log: ${LOG_FILE}`);
  } finally {
    await c.stop();
    resetDemoData();
  }
})().catch((e) => { console.error(e); process.exit(1); });
