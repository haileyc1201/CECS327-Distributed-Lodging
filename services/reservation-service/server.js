/**
 * Reservation Service — Express HTTP on :5002
 * Calls Property (:5001) and Payment (:5003) over HTTP.
 * GET /reservations, POST /reservations, POST /reservations/cancel
 */
const express = require('express');
const crypto = require('crypto');
const {
  loadReservations,
  saveReservations,
  appendLog,
} = require('../shared/csv');

const HOST = process.env.RESERVATION_HOST || '127.0.0.1';
const PORT = Number(process.env.RESERVATION_PORT || 5002);
const PROPERTY_URL = process.env.PROPERTY_URL || 'http://127.0.0.1:5001';
const PAYMENT_URL = process.env.PAYMENT_URL || 'http://127.0.0.1:5003';

const app = express();
app.use(express.json());

function log(message) {
  console.log(`[RESERVATION] ${message}`);
  appendLog('reservation', message);
}

function shortId(prefix) {
  return `${prefix}-${crypto.randomBytes(4).toString('hex')}`;
}

async function httpJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

async function getProperty(propertyId) {
  const { data } = await httpJson(`${PROPERTY_URL}/properties/${propertyId}`);
  return data;
}

async function setAvailability(propertyId, available) {
  const { data } = await httpJson(`${PROPERTY_URL}/properties/${propertyId}/availability`, {
    method: 'PATCH',
    body: JSON.stringify({ available }),
  });
  return data;
}

async function processPayment(propertyId, amount, guestName) {
  const { data } = await httpJson(`${PAYMENT_URL}/payments`, {
    method: 'POST',
    body: JSON.stringify({
      property_id: propertyId,
      amount,
      guest_name: guestName,
    }),
  });
  return data;
}

async function refundPayment(paymentId, amount, reservationId) {
  const { data } = await httpJson(`${PAYMENT_URL}/refunds`, {
    method: 'POST',
    body: JSON.stringify({
      payment_id: paymentId,
      amount,
      reservation_id: reservationId,
    }),
  });
  return data;
}

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'reservation' });
});

app.get('/reservations', (_req, res) => {
  try {
    const reservations = loadReservations();
    log(`list_reservations -> ${reservations.length}`);
    res.json({ status: 'success', reservations });
  } catch (err) {
    log(`list error: ${err.message}`);
    res.status(500).json({ status: 'error', message: err.message });
  }
});

app.post('/reservations', async (req, res) => {
  try {
    const propertyId = req.body?.property_id;
    const guestName = req.body?.guest_name || 'Guest';

    if (propertyId == null) {
      return res.status(400).json({ status: 'rejected', message: 'property_id is required' });
    }

    const propertyResponse = await getProperty(propertyId);
    log(`Property Service replied: ${JSON.stringify(propertyResponse)}`);

    if (propertyResponse.status !== 'success') {
      return res.status(400).json({ status: 'rejected', message: 'Property does not exist' });
    }

    const prop = propertyResponse.property;
    if (!prop.available) {
      return res.status(400).json({ status: 'rejected', message: 'Property is not available' });
    }

    const amount = prop.price || 0;
    const paymentResponse = await processPayment(propertyId, amount, guestName);
    log(`Payment Service replied: ${JSON.stringify(paymentResponse)}`);

    if (paymentResponse.status !== 'approved') {
      return res.status(400).json({
        status: 'rejected',
        message: 'Payment declined',
        payment: paymentResponse,
      });
    }

    const reservation = {
      reservation_id: shortId('res'),
      property_id: Number(propertyId),
      property_name: prop.name,
      guest_name: guestName,
      amount,
      payment_id: paymentResponse.payment_id,
      refund_id: null,
      status: 'confirmed',
      created_at: new Date().toISOString(),
      cancelled_at: null,
    };

    const reservations = loadReservations();
    reservations.push(reservation);
    saveReservations(reservations);
    await setAvailability(propertyId, false);
    log(`Saved ${reservation.reservation_id}; property ${propertyId} unavailable`);

    return res.json({
      status: 'accepted',
      message: 'Reservation confirmed',
      reservation,
      payment: paymentResponse,
    });
  } catch (err) {
    log(`book error: ${err.message}`);
    return res.status(502).json({ status: 'error', message: err.message });
  }
});

app.post('/reservations/cancel', async (req, res) => {
  try {
    const reservationId = req.body?.reservation_id;
    if (!reservationId) {
      return res.status(400).json({ status: 'rejected', message: 'reservation_id is required' });
    }

    const reservations = loadReservations();
    const target = reservations.find((r) => r.reservation_id === reservationId);
    if (!target) {
      return res.status(400).json({ status: 'rejected', message: 'Reservation not found' });
    }
    if (target.status === 'cancelled') {
      return res.status(400).json({
        status: 'rejected',
        message: 'Reservation already cancelled',
        reservation: target,
      });
    }

    let refundResponse = null;
    if (target.payment_id) {
      refundResponse = await refundPayment(
        target.payment_id,
        target.amount || 0,
        reservationId,
      );
      log(`Payment Service refund replied: ${JSON.stringify(refundResponse)}`);
      if (refundResponse.status !== 'refunded') {
        return res.status(400).json({
          status: 'rejected',
          message: 'Refund failed; reservation not cancelled',
          refund: refundResponse,
        });
      }
    }

    target.status = 'cancelled';
    target.cancelled_at = new Date().toISOString();
    if (refundResponse) {
      target.refund_id = refundResponse.refund_id;
    }

    saveReservations(reservations);
    await setAvailability(target.property_id, true);
    log(`Cancelled ${reservationId}; property ${target.property_id} available again`);

    return res.json({
      status: 'cancelled',
      message: 'Reservation cancelled and payment refunded',
      reservation: target,
      refund: refundResponse,
    });
  } catch (err) {
    log(`cancel error: ${err.message}`);
    return res.status(502).json({ status: 'error', message: err.message });
  }
});

app.listen(PORT, HOST, () => {
  loadReservations();
  log(`Listening on http://${HOST}:${PORT}`);
});
