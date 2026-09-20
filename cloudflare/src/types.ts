/** Cloudflare Worker env bindings */
export type Env = {
  DB: D1Database
  ASSETS: Fetcher
}

export type Property = {
  id: number
  name: string
  price: number
  available: boolean
  city: string
  beds: number
}

export type Reservation = {
  reservation_id: string
  property_id: number
  property_name: string
  guest_name: string
  amount: number
  payment_id: string | null
  refund_id: string | null
  status: string
  created_at: string | null
  cancelled_at: string | null
}

export type LogEntry = {
  file: string
  line: string
}

export type PaymentResult = {
  status: 'approved' | 'declined'
  payment_id: string
  message: string
}

export type RefundResult = {
  status: 'refunded' | 'declined'
  refund_id: string
  payment_id?: string
  reservation_id?: string
  amount?: number
  message: string
}
