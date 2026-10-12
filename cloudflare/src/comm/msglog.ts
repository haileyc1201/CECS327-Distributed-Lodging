/**
 * ISO-8601 timestamped message log persisted in D1 (table message_log), so the
 * log survives across Worker isolates and is retrievable via GET /api/comm/logs.
 * Each SEND entry stores the message before marshalling and the wire text after;
 * each RECV entry stores the wire text before unmarshalling and the result after.
 */
import { nowIso, type Envelope, type WireFormat } from './marshal'

export const MESSAGE_LOG_SCHEMA = `CREATE TABLE IF NOT EXISTS message_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  node TEXT NOT NULL,
  event TEXT NOT NULL,
  peer TEXT,
  format TEXT,
  bytes INTEGER,
  msg_type TEXT,
  msg_id TEXT,
  note TEXT,
  message TEXT,
  wire TEXT
)`

let schemaReady = false
export async function ensureSchema(db: D1Database): Promise<void> {
  if (schemaReady) return
  await db.prepare(MESSAGE_LOG_SCHEMA).run()
  schemaReady = true
}

export type LogRow = {
  ts: string
  node: string
  event: 'SEND' | 'RECV' | 'INFO'
  peer?: string
  format?: WireFormat
  bytes?: number
  message?: Envelope
  wire?: string
  note?: string
}

const enc = new TextEncoder()

/** Buffers entries for one request and writes them to D1 in a single batch. */
export class MessageLog {
  private rows: LogRow[] = []
  constructor(private db: D1Database) {}

  send(node: string, peer: string, message: Envelope, wire: string, format: WireFormat) {
    this.push({ ts: nowIso(), node, event: 'SEND', peer, format, bytes: enc.encode(wire).length, message, wire })
  }
  recv(node: string, peer: string, wire: string, message: Envelope, format: WireFormat) {
    this.push({ ts: nowIso(), node, event: 'RECV', peer, format, bytes: enc.encode(wire).length, message, wire })
  }
  info(node: string, note: string) {
    this.push({ ts: nowIso(), node, event: 'INFO', note })
  }
  private push(r: LogRow) {
    this.rows.push(r)
    const m = r.message
    console.log(`${r.ts} [${r.node}] ${r.event} ${r.peer || ''} type=${m?.type || ''} id=${m?.id || ''} ${r.note || ''}`)
  }

  async flush(): Promise<void> {
    if (!this.rows.length) return
    const rows = this.rows.splice(0)
    await ensureSchema(this.db)
    const stmt = this.db.prepare(
      `INSERT INTO message_log (ts, node, event, peer, format, bytes, msg_type, msg_id, note, message, wire)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    await this.db.batch(
      rows.map((r) =>
        stmt.bind(
          r.ts, r.node, r.event, r.peer ?? null, r.format ?? null, r.bytes ?? null,
          r.message?.type ?? null, r.message?.id ?? null, r.note ?? null,
          r.message ? JSON.stringify(r.message) : null, r.wire ?? null,
        ),
      ),
    )
    // keep the table bounded
    if (Math.random() < 0.05) {
      await this.db.prepare('DELETE FROM message_log WHERE id < (SELECT MAX(id) - 5000 FROM message_log)').run()
    }
  }
}

export async function readMessageLog(db: D1Database, limit = 200, node?: string) {
  await ensureSchema(db)
  const q = node
    ? db.prepare('SELECT * FROM message_log WHERE node = ? ORDER BY id DESC LIMIT ?').bind(node, limit)
    : db.prepare('SELECT * FROM message_log ORDER BY id DESC LIMIT ?').bind(limit)
  const { results } = await q.all<Record<string, unknown>>()
  return (results || []).reverse().map((r) => ({
    ts: r.ts, node: r.node, event: r.event, peer: r.peer, format: r.format, bytes: r.bytes, note: r.note,
    message: r.message ? JSON.parse(String(r.message)) : undefined,
    wire: r.wire ?? undefined,
  }))
}
