import type { LogEntry } from './types'

/** In-memory ring buffer of recent service messages (per isolate). */
const MAX_LOGS = 200
const buffer: LogEntry[] = []

export function appendLog(serviceName: string, message: string): void {
  const entry: LogEntry = {
    file: `${serviceName}.log`,
    line: JSON.stringify({ ts: new Date().toISOString(), message }),
  }
  buffer.push(entry)
  if (buffer.length > MAX_LOGS) {
    buffer.splice(0, buffer.length - MAX_LOGS)
  }
  console.log(`[${serviceName.toUpperCase()}] ${message}`)
}

export function readRecentLogs(maxLines = 100): LogEntry[] {
  return buffer.slice(-maxLines)
}
