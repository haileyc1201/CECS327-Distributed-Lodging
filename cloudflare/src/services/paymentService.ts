/**
 * Payment Service — mock approve / refund (no external processor).
 * Mirrors Node Express payment-service behavior.
 */
import { appendLog } from '../logger'
import type { PaymentResult, RefundResult } from '../types'

function shortId(prefix: string): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${prefix}-${hex}`
}

function log(message: string) {
  appendLog('payment', message)
}

export function processPayment(
  propertyId: number | string | null | undefined,
  amount: number | string | null | undefined,
  guestName = 'Guest',
): PaymentResult {
  const payment_id = shortId('pay')
  log(`process_payment ${JSON.stringify({ property_id: propertyId, amount, guest_name: guestName })}`)

  if (propertyId == null) {
    return { status: 'declined', payment_id, message: 'Missing property_id' }
  }
  if (amount == null) {
    return { status: 'declined', payment_id, message: 'Missing amount' }
  }

  const amountVal = Number(amount)
  if (Number.isNaN(amountVal)) {
    return { status: 'declined', payment_id, message: 'Invalid amount' }
  }
  if (amountVal <= 0) {
    return { status: 'declined', payment_id, message: 'Amount must be greater than 0' }
  }

  const response: PaymentResult = {
    status: 'approved',
    payment_id,
    message: `Payment of $${amountVal.toFixed(2)} approved for ${guestName}`,
  }
  log(`approved ${payment_id}`)
  return response
}

export function refundPayment(
  paymentId: string | null | undefined,
  amount: number | string | null | undefined,
  reservationId?: string,
): RefundResult {
  const refund_id = shortId('ref')
  log(`refund ${JSON.stringify({ payment_id: paymentId, amount, reservation_id: reservationId })}`)

  if (!paymentId) {
    return { status: 'declined', refund_id, message: 'Missing payment_id' }
  }

  let amountVal = 0
  try {
    amountVal = amount != null ? Number(amount) : 0
    if (Number.isNaN(amountVal)) throw new Error('nan')
  } catch {
    return { status: 'declined', refund_id, message: 'Invalid amount' }
  }

  const response: RefundResult = {
    status: 'refunded',
    refund_id,
    payment_id: paymentId,
    reservation_id: reservationId,
    amount: amountVal,
    message: `Refund of $${amountVal.toFixed(2)} issued for payment ${paymentId}`,
  }
  log(`refunded ${refund_id}`)
  return response
}
