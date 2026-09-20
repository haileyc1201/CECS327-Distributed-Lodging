/**
 * HTTP Gateway — Express on :8000
 * Proxies /api/* to Property / Reservation services; hard reset + logs.
 */
const express = require('express');
const cors = require('cors');
const { resetDemoData, readRecentLogs, appendLog } = require('../shared/csv');

const HOST = process.env.GATEWAY_HOST || '127.0.0.1';
const PORT = Number(process.env.GATEWAY_PORT || 8000);
const PROPERTY_URL = process.env.PROPERTY_URL || 'http://127.0.0.1:5001';
const RESERVATION_URL = process.env.RESERVATION_URL || 'http://127.0.0.1:5002';

const app = express();
app.use(cors());
app.use(express.json());

function log(message) {
  console.log(`[GATEWAY] ${message}`);
  appendLog('gateway', message);
}

async function proxyJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json();
  return { httpStatus: res.status, data };
}

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.get('/api/properties', async (_req, res) => {
  try {
    const { data } = await proxyJson(`${PROPERTY_URL}/properties`);
    res.json(data);
  } catch (err) {
    log(`properties error: ${err.message}`);
    res.status(502).json({ status: 'error', message: err.message });
  }
});

app.get('/api/properties/:id', async (req, res) => {
  try {
    const { httpStatus, data } = await proxyJson(`${PROPERTY_URL}/properties/${req.params.id}`);
    res.status(httpStatus).json(data);
  } catch (err) {
    log(`get property error: ${err.message}`);
    res.status(502).json({ status: 'error', message: err.message });
  }
});

app.post('/api/reservations', async (req, res) => {
  const body = req.body || {};
  if (body.property_id == null) {
    return res.status(400).json({ status: 'rejected', message: 'property_id is required' });
  }
  try {
    const { httpStatus, data } = await proxyJson(`${RESERVATION_URL}/reservations`, {
      method: 'POST',
      body: JSON.stringify({
        property_id: Number(body.property_id),
        guest_name: body.guest_name || 'Guest',
      }),
    });
    const code = data.status === 'accepted' ? 200 : httpStatus >= 400 ? httpStatus : 400;
    return res.status(code).json(data);
  } catch (err) {
    log(`book error: ${err.message}`);
    return res.status(502).json({ status: 'error', message: err.message });
  }
});

app.get('/api/reservations', async (_req, res) => {
  try {
    const { data } = await proxyJson(`${RESERVATION_URL}/reservations`);
    res.json(data);
  } catch (err) {
    log(`list reservations error: ${err.message}`);
    res.status(502).json({ status: 'error', message: err.message });
  }
});

app.post('/api/reservations/cancel', async (req, res) => {
  const reservationId = req.body?.reservation_id;
  if (!reservationId) {
    return res.status(400).json({ status: 'rejected', message: 'reservation_id is required' });
  }
  try {
    const { httpStatus, data } = await proxyJson(`${RESERVATION_URL}/reservations/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reservation_id: reservationId }),
    });
    const code = data.status === 'cancelled' ? 200 : httpStatus >= 400 ? httpStatus : 400;
    return res.status(code).json(data);
  } catch (err) {
    log(`cancel error: ${err.message}`);
    return res.status(502).json({ status: 'error', message: err.message });
  }
});

app.delete('/api/reservations/:id', async (req, res) => {
  try {
    const { httpStatus, data } = await proxyJson(`${RESERVATION_URL}/reservations/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reservation_id: req.params.id }),
    });
    const code = data.status === 'cancelled' ? 200 : httpStatus >= 400 ? httpStatus : 400;
    return res.status(code).json(data);
  } catch (err) {
    log(`delete cancel error: ${err.message}`);
    return res.status(502).json({ status: 'error', message: err.message });
  }
});

app.post('/api/reset', (_req, res) => {
  try {
    resetDemoData();
    log('Demo data reset');
    res.json({ status: 'ok', message: 'Demo data reset' });
  } catch (err) {
    log(`reset error: ${err.message}`);
    res.status(500).json({ status: 'error', message: err.message });
  }
});

app.get('/api/logs', (_req, res) => {
  try {
    const logs = readRecentLogs(100);
    res.json({ status: 'ok', logs });
  } catch (err) {
    res.status(500).json({ status: 'error', message: err.message });
  }
});

app.listen(PORT, HOST, () => {
  log(`Listening on http://${HOST}:${PORT}`);
});
