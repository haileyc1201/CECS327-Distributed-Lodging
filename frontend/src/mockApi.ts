import { cloneSeedProperties, type SeedProperty } from './seedProperties'

export type MockReservation = {
  reservation_id: string
  property_id: number
  property_name?: string
  guest_name: string
  amount: number
  payment_id?: string
  refund_id?: string
  status?: string
  created_at?: string
  cancelled_at?: string
}

export type MockLog = { file: string; line: string }

type Store = {
  properties: SeedProperty[]
  reservations: MockReservation[]
  logs: MockLog[]
}

const store: Store = {
  properties: cloneSeedProperties(),
  reservations: [],
  logs: [],
}

function log(message: string) {
  store.logs.push({
    file: 'demo.log',
    line: JSON.stringify({ ts: new Date().toISOString(), message }),
  })
  if (store.logs.length > 100) store.logs = store.logs.slice(-100)
}

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(16).slice(2, 10)}`
}

export const mockApi = {
  listProperties() {
    return { status: 'success' as const, properties: store.properties.map((p) => ({ ...p })) }
  },
  listReservations() {
    return { status: 'success' as const, reservations: store.reservations.map((r) => ({ ...r })) }
  },
  getLogs() {
    return { status: 'ok' as const, logs: [...store.logs] }
  },
  book(propertyId: number, guestName: string) {
    const prop = store.properties.find((p) => p.id === propertyId)
    if (!prop) {
      return { status: 'rejected' as const, message: 'Property does not exist' }
    }
    if (!prop.available) {
      return { status: 'rejected' as const, message: 'Property is not available' }
    }
    const paymentId = uid('pay')
    const reservation: MockReservation = {
      reservation_id: uid('res'),
      property_id: propertyId,
      property_name: prop.name,
      guest_name: guestName,
      amount: prop.price,
      payment_id: paymentId,
      status: 'confirmed',
      created_at: new Date().toISOString(),
    }
    prop.available = false
    store.reservations.push(reservation)
    log(`Mock booked ${reservation.reservation_id} for property ${propertyId}`)
    return {
      status: 'accepted' as const,
      message: 'Reservation confirmed',
      reservation,
      payment: { status: 'approved', payment_id: paymentId, message: 'Mock payment approved' },
    }
  },
  cancel(reservationId: string) {
    const target = store.reservations.find((r) => r.reservation_id === reservationId)
    if (!target) {
      return { status: 'rejected' as const, message: 'Reservation not found' }
    }
    if (target.status === 'cancelled') {
      return {
        status: 'rejected' as const,
        message: 'Reservation already cancelled',
        reservation: target,
      }
    }
    const refundId = uid('ref')
    target.status = 'cancelled'
    target.cancelled_at = new Date().toISOString()
    target.refund_id = refundId
    const prop = store.properties.find((p) => p.id === target.property_id)
    if (prop) prop.available = true
    log(`Mock cancelled ${reservationId}; property ${target.property_id} available`)
    return {
      status: 'cancelled' as const,
      message: 'Reservation cancelled and payment refunded',
      reservation: target,
      refund: { status: 'refunded', refund_id: refundId, message: 'Mock refund complete' },
    }
  },
  reset() {
    store.properties = cloneSeedProperties()
    store.reservations = []
    log('Mock demo data reset')
    return { status: 'ok' as const, message: 'Demo data reset' }
  },
}
