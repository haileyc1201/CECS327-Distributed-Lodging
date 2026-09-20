/**
 * Reservation Service — book/cancel orchestrating property + payment modules.
 * Mirrors Node Express reservation-service behavior (in-process instead of HTTP).
 */
import { appendLog } from '../logger'
import { processPayment, refundPayment } from './paymentService'
import {
  findProperty,
  listProperties,
  resetSeedAvailability,
  setPropertyAvailable,
} from './propertyService'
import type { Reservation } from '../types'

type ReservationRow = {
  reservation_id: string
  property_id: number
  property_name: string | null
  guest_name: string | null
  amount: number | null
  payment_id: string | null
  refund_id: string | null
  status: string | null
  created_at: string | null
  cancelled_at: string | null
}

function shortId(prefix: string): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${prefix}-${hex}`
}

function log(message: string) {
  appendLog('reservation', message)
}

function rowToReservation(row: ReservationRow): Reservation {
  return {
    reservation_id: row.reservation_id,
    property_id: row.property_id,
    property_name: row.property_name || '',
    guest_name: row.guest_name || '',
    amount: row.amount != null ? Number(row.amount) : 0,
    payment_id: row.payment_id || null,
    refund_id: row.refund_id || null,
    status: row.status || 'confirmed',
    created_at: row.created_at || null,
    cancelled_at: row.cancelled_at || null,
  }
}

export async function listReservations(db: D1Database): Promise<Reservation[]> {
  const { results } = await db
    .prepare(
      `SELECT reservation_id, property_id, property_name, guest_name, amount,
              payment_id, refund_id, status, created_at, cancelled_at
       FROM reservations
       ORDER BY created_at DESC`,
    )
    .all<ReservationRow>()
  const reservations = (results || []).map(rowToReservation)
  log(`list_reservations -> ${reservations.length}`)
  return reservations
}

async function getReservation(
  db: D1Database,
  reservationId: string,
): Promise<Reservation | null> {
  const row = await db
    .prepare(
      `SELECT reservation_id, property_id, property_name, guest_name, amount,
              payment_id, refund_id, status, created_at, cancelled_at
       FROM reservations WHERE reservation_id = ?`,
    )
    .bind(reservationId)
    .first<ReservationRow>()
  return row ? rowToReservation(row) : null
}

export async function bookReservation(
  db: D1Database,
  propertyId: number | string,
  guestName = 'Guest',
): Promise<{ httpStatus: number; body: Record<string, unknown> }> {
  if (propertyId == null || propertyId === '') {
    return {
      httpStatus: 400,
      body: { status: 'rejected', message: 'property_id is required' },
    }
  }

  const prop = await findProperty(db, propertyId)
  log(`Property Service replied: ${JSON.stringify(prop ? { status: 'success', property: prop } : { status: 'error' })}`)

  if (!prop) {
    return {
      httpStatus: 400,
      body: { status: 'rejected', message: 'Property does not exist' },
    }
  }
  if (!prop.available) {
    return {
      httpStatus: 400,
      body: { status: 'rejected', message: 'Property is not available' },
    }
  }

  const amount = prop.price || 0
  const paymentResponse = processPayment(propertyId, amount, guestName)
  log(`Payment Service replied: ${JSON.stringify(paymentResponse)}`)

  if (paymentResponse.status !== 'approved') {
    return {
      httpStatus: 400,
      body: {
        status: 'rejected',
        message: 'Payment declined',
        payment: paymentResponse,
      },
    }
  }

  const reservation: Reservation = {
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
  }

  await db
    .prepare(
      `INSERT INTO reservations
        (reservation_id, property_id, property_name, guest_name, amount,
         payment_id, refund_id, status, created_at, cancelled_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      reservation.reservation_id,
      reservation.property_id,
      reservation.property_name,
      reservation.guest_name,
      reservation.amount,
      reservation.payment_id,
      reservation.refund_id,
      reservation.status,
      reservation.created_at,
      reservation.cancelled_at,
    )
    .run()

  await setPropertyAvailable(db, propertyId, false)
  log(`Saved ${reservation.reservation_id}; property ${propertyId} unavailable`)

  return {
    httpStatus: 200,
    body: {
      status: 'accepted',
      message: 'Reservation confirmed',
      reservation,
      payment: paymentResponse,
    },
  }
}

export async function cancelReservation(
  db: D1Database,
  reservationId: string | null | undefined,
): Promise<{ httpStatus: number; body: Record<string, unknown> }> {
  if (!reservationId) {
    return {
      httpStatus: 400,
      body: { status: 'rejected', message: 'reservation_id is required' },
    }
  }

  const target = await getReservation(db, reservationId)
  if (!target) {
    return {
      httpStatus: 400,
      body: { status: 'rejected', message: 'Reservation not found' },
    }
  }
  if (target.status === 'cancelled') {
    return {
      httpStatus: 400,
      body: {
        status: 'rejected',
        message: 'Reservation already cancelled',
        reservation: target,
      },
    }
  }

  let refundResponse = null
  if (target.payment_id) {
    refundResponse = refundPayment(
      target.payment_id,
      target.amount || 0,
      reservationId,
    )
    log(`Payment Service refund replied: ${JSON.stringify(refundResponse)}`)
    if (refundResponse.status !== 'refunded') {
      return {
        httpStatus: 400,
        body: {
          status: 'rejected',
          message: 'Refund failed; reservation not cancelled',
          refund: refundResponse,
        },
      }
    }
  }

  const cancelledAt = new Date().toISOString()
  const refundId = refundResponse?.refund_id ?? null

  await db
    .prepare(
      `UPDATE reservations
       SET status = 'cancelled', cancelled_at = ?, refund_id = ?
       WHERE reservation_id = ?`,
    )
    .bind(cancelledAt, refundId, reservationId)
    .run()

  await setPropertyAvailable(db, target.property_id, true)
  log(`Cancelled ${reservationId}; property ${target.property_id} available again`)

  const updated: Reservation = {
    ...target,
    status: 'cancelled',
    cancelled_at: cancelledAt,
    refund_id: refundId,
  }

  return {
    httpStatus: 200,
    body: {
      status: 'cancelled',
      message: 'Reservation cancelled and payment refunded',
      reservation: updated,
      refund: refundResponse,
    },
  }
}

export async function resetDemoData(db: D1Database): Promise<void> {
  await db.prepare('DELETE FROM reservations').run()
  await resetSeedAvailability(db)
  // Touch properties so list still returns 12 seed rows
  const props = await listProperties(db)
  log(`Demo data reset — ${props.length} properties, 0 reservations`)
}
