/**
 * Payment Service — Express HTTP on :5003
 * POST /payments, POST /refunds
 */
const express = require('express');
const crypto = require('crypto');
const { appendLog } = require('../shared/csv');

const HOST = process.env.PAYMENT_HOST || '127.0.0.1';
const PORT = Number(process.env.PAYMENT_PORT || 5003);

const app = express();
app.use(express.json());

function log(message) {
  console.log(`[PAYMENT] ${message}`);
  appendLog('payment', message);
}

function shortId(prefix) {
  return `${prefix}-${crypto.randomBytes(4).toString('hex')}`;
}

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'payment' });
});

app.post('/payments', (req, res) => {
  const { property_id, amount, guest_name = 'Guest' } = req.body || {};
  const payment_id = shortId('pay');
  log(`process_payment ${JSON.stringify({ property_id, amount, guest_name })}`);

  if (property_id == null) {
    return res.status(400).json({
      status: 'declined',
      payment_id,
      message: 'Missing property_id',
    });
  }
  if (amount == null) {
    return res.status(400).json({
      status: 'declined',
      payment_id,
      message: 'Missing amount',
    });
  }

  const amountVal = Number(amount);
  if (Number.isNaN(amountVal)) {
    return res.status(400).json({
      status: 'declined',
      payment_id,
      message: 'Invalid amount',
    });
  }
  if (amountVal <= 0) {
    return res.status(400).json({
      status: 'declined',
      payment_id,
      message: 'Amount must be greater than 0',
    });
  }

  const response = {
    status: 'approved',
    payment_id,
    message: `Payment of $${amountVal.toFixed(2)} approved for ${guest_name}`,
  };
  log(`approved ${payment_id}`);
  return res.json(response);
});

app.post('/refunds', (req, res) => {
  const { payment_id, amount, reservation_id } = req.body || {};
  const refund_id = shortId('ref');
  log(`refund ${JSON.stringify({ payment_id, amount, reservation_id })}`);

  if (!payment_id) {
    return res.status(400).json({
      status: 'declined',
      refund_id,
      message: 'Missing payment_id',
    });
  }

  let amountVal = 0;
  try {
    amountVal = amount != null ? Number(amount) : 0;
    if (Number.isNaN(amountVal)) throw new Error('nan');
  } catch {
    return res.status(400).json({
      status: 'declined',
      refund_id,
      message: 'Invalid amount',
    });
  }

  const response = {
    status: 'refunded',
    refund_id,
    payment_id,
    reservation_id,
    amount: amountVal,
    message: `Refund of $${amountVal.toFixed(2)} issued for payment ${payment_id}`,
  };
  log(`refunded ${refund_id}`);
  return res.json(response);
});

app.listen(PORT, HOST, () => {
  log(`Listening on http://${HOST}:${PORT}`);
});
