/** Starts every Node service + comm nodes as separate processes (used by the demo and tests). */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');

async function waitFor(url, ms = 10000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch { /* not yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`timeout waiting for ${url}`);
}

async function startCluster({ base = 5000, env = {}, quietOut = true } = {}) {
  const p = {
    property: base + 1, reservation: base + 2, payment: base + 3, hub: base + 10, gateway: base + 3000,
  };
  const urls = Object.fromEntries(Object.entries(p).map(([k, v]) => [k, `http://127.0.0.1:${v}`]));
  const common = {
    ...process.env, ...env,
    PROPERTY_PORT: p.property, RESERVATION_PORT: p.reservation, PAYMENT_PORT: p.payment, HUB_PORT: p.hub,
    GATEWAY_PORT: p.gateway, PROPERTY_URL: urls.property, RESERVATION_URL: urls.reservation,
    PAYMENT_URL: urls.payment, HUB_URL: urls.hub,
  };
  fs.mkdirSync(path.join(ROOT, 'logs'), { recursive: true });
  const procs = {};
  const run = (name, args) => {
    const out = quietOut ? fs.openSync(path.join(ROOT, 'logs', `${name}.out`), 'w') : 'inherit';
    procs[name] = spawn(process.execPath, args, { cwd: ROOT, env: common, stdio: ['ignore', out, out] });
  };
  run('property', ['services/property-service/server.js']);
  run('payment', ['services/payment-service/server.js']);
  run('hub', ['services/comm-hub/server.js']);
  await Promise.all([waitFor(`${urls.property}/health`).catch(() => waitFor(`${urls.property}/properties`)),
    waitFor(`${urls.hub}/health`)]);
  run('reservation', ['services/reservation-service/server.js']);
  run('gateway', ['services/gateway/server.js']);
  await waitFor(`${urls.reservation}/health`);
  await waitFor(`${urls.gateway}/api/health`);
  const subs = ['notification-service', 'analytics-service', 'audit-service'];
  subs.forEach((n, i) => run(n, ['services/comm-hub/node.js', 'subscriber', n, String(base + 101 + i), 'booking.created']));
  const replicas = ['replica-1', 'replica-2', 'replica-3'];
  replicas.forEach((n, i) => run(n, ['services/comm-hub/node.js', 'member', n, String(base + 201 + i), 'property-replicas']));
  const nodeUrl = (n) => {
    const i = subs.indexOf(n);
    return `http://127.0.0.1:${i >= 0 ? base + 101 + i : base + 201 + replicas.indexOf(n)}`;
  };
  // wait for all registrations
  const end = Date.now() + 10000;
  while (Date.now() < end) {
    const s = await (await fetch(`${urls.hub}/subscribers`)).json();
    const g = await (await fetch(`${urls.hub}/group/members?group=property-replicas`)).json();
    if ((s['booking.created'] || []).length === 3 && g.members.length === 3) break;
    await new Promise((r) => setTimeout(r, 100));
  }
  const kill = (name, sig = 'SIGTERM') => new Promise((resolve) => {
    const c = procs[name];
    if (!c || c.exitCode !== null || c.signalCode !== null) return resolve();
    c.once('exit', resolve);
    c.kill(sig);
  });
  const stop = async () => { await Promise.all(Object.keys(procs).map((n) => kill(n))); };
  return { urls, procs, subs, replicas, nodeUrl, kill, stop };
}

module.exports = { startCluster, ROOT };
