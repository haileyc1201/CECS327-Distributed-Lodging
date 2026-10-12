/**
 * A communication node process. Runs its own HTTP listener and either
 *   - subscribes to a topic   (role "subscriber"), or
 *   - joins a group           (role "member", e.g. a property-cache replica).
 *
 *   node services/comm-hub/node.js subscriber notification-service 5101 booking.created
 *   node services/comm-hub/node.js member replica-1 5201 property-replicas
 */
const express = require('express');
const { makeEnvelope, makeLogger, sendMessage, envelopeBody, replyEnvelope } = require('../shared/messaging');

const [role, name, portArg, target] = process.argv.slice(2);
const PORT = Number(portArg);
const HUB = process.env.HUB_URL || 'http://127.0.0.1:5010';
const logger = makeLogger(name);
const state = { received: [], view: [], cache: {} };

const ACTIONS = {
  'notification-service': (e) => `send confirmation email to ${e.guest_name} for ${e.property_name}`,
  'analytics-service': (e) => `record revenue $${e.amount} for property ${e.property_id}`,
  'audit-service': (e) => `append audit record for ${e.reservation_id}`,
};

const app = express();
app.post('/deliver', envelopeBody(logger), (req, res) => {
  const env = req.envelope;
  const p = env.payload || {};
  let ackType = 'event.ack';
  if (env.type === 'event') {
    state.received.push(p);
    const action = ACTIONS[name] ? ACTIONS[name](p.event) : `received ${p.event?.reservation_id}`;
    logger.info(action);
  } else if (env.type === 'group.deliver') {
    ackType = 'group.ack';
    state.received.push(p);
    if (p.message?.op === 'availability_update') state.cache[p.message.property_id] = p.message.available;
    logger.info(`replica state now ${JSON.stringify(state.cache)}`);
  } else if (env.type === 'group.view') {
    ackType = 'group.ack';
    state.view = p.members;
  }
  replyEnvelope(logger, req, res, makeEnvelope(ackType, name, { seq: p.seq ?? p.view_id, member: name },
    { receiver: env.sender, correlationId: env.id }));
});
app.get('/state', (_req, res) => res.json({ name, role, ...state }));

app.listen(PORT, '127.0.0.1', async () => {
  const url = `http://127.0.0.1:${PORT}/deliver`;
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      if (role === 'subscriber') {
        await sendMessage(logger, `${HUB}/subscribe`, makeEnvelope('subscribe', name, { topic: target, name, url }));
      } else {
        await sendMessage(logger, `${HUB}/group/join`, makeEnvelope('group.join', name, { group: target, member: name, url }));
      }
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  logger.info('could not reach comm hub');
});

async function shutdown() {
  if (role === 'member') {
    try {
      await sendMessage(logger, `${HUB}/group/leave`, makeEnvelope('group.leave', name, { group: target, member: name }), 'json', 1000);
    } catch { /* hub gone */ }
  }
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGUSR2', shutdown);
