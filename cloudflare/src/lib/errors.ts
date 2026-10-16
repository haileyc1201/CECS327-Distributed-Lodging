/**
 * Error masking helper (Cloudflare Worker).
 * Same idea as services/shared/errors.js: log the full error with a reference ID,
 * send the client only a generic message plus that ID.
 */
export const GENERIC_MESSAGE = 'Something went wrong. Please try again.'

export interface MaskedError {
  status: 'error'
  message: string
  ref: string
}

export function makeRef(): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function describe(err: unknown): string {
  if (err instanceof Error) return err.stack || err.message
  return typeof err === 'string' ? err : JSON.stringify(err)
}

export function maskError(log: (m: string) => void, context: string, err: unknown): MaskedError {
  const ref = makeRef()
  log(`${context} [ref ${ref}]: ${describe(err)}`)
  return { status: 'error', message: GENERIC_MESSAGE, ref }
}

export function rpcError(
  log: (m: string) => void,
  context: string,
  err: unknown,
): { code: number; message: string; data?: unknown } {
  const e = err as { name?: string; code?: unknown; message?: string; data?: unknown }
  if (e && e.name === 'RpcError' && Number.isInteger(e.code)) {
    return { code: e.code as number, message: String(e.message), data: e.data }
  }
  const ref = makeRef()
  log(`${context} [ref ${ref}]: ${describe(err)}`)
  return { code: -32603, message: GENERIC_MESSAGE, data: { ref } }
}
