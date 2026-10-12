/**
 * Envelope + marshalling (JSON / typed XML) — same wire format as the Node
 * services (services/shared/messaging.js) and the Python simulation on main.
 */
export type Envelope = {
  id: string
  type: string
  sender: string
  receiver: string | null
  timestamp: string
  correlation_id: string | null
  payload: unknown
}
export type WireFormat = 'json' | 'xml'
export const CONTENT_TYPES: Record<WireFormat, string> = { json: 'application/json', xml: 'application/xml' }

export const nowIso = () => new Date().toISOString()

function hexId(n = 6): string {
  const b = new Uint8Array(n)
  crypto.getRandomValues(b)
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
}

export function makeEnvelope(
  type: string,
  sender: string,
  payload: unknown,
  opts: { receiver?: string | null; correlationId?: string | null } = {},
): Envelope {
  return {
    id: hexId(),
    type,
    sender,
    receiver: opts.receiver ?? null,
    timestamp: nowIso(),
    correlation_id: opts.correlationId ?? null,
    payload,
  }
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const unesc = (s: string) => s.replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&')

function toXml(tag: string, v: unknown): string {
  if (v === null || v === undefined) return `<${tag} t="null"/>`
  if (typeof v === 'boolean') return `<${tag} t="bool">${v}</${tag}>`
  if (typeof v === 'number') return `<${tag} t="${Number.isInteger(v) ? 'int' : 'float'}">${v}</${tag}>`
  if (typeof v === 'string') return `<${tag} t="str">${esc(v)}</${tag}>`
  if (Array.isArray(v)) return `<${tag} t="list">${v.map((x) => toXml('item', x)).join('')}</${tag}>`
  return `<${tag} t="dict">${Object.entries(v as Record<string, unknown>)
    .map(([k, x]) => `<entry key="${esc(k)}">${toXml('value', x)}</entry>`)
    .join('')}</${tag}>`
}

type XNode = { tag: string; attrs: Record<string, string>; children: XNode[]; text: string }

function parseXml(src: string): XNode {
  let i = 0
  const ws = () => {
    while (/\s/.test(src[i] || '')) i++
  }
  function node(): XNode {
    ws()
    if (src.startsWith('<?', i)) {
      i = src.indexOf('?>', i) + 2
      ws()
    }
    if (src[i] !== '<') throw new Error(`XML parse error at ${i}`)
    i++
    const tagEnd = src.slice(i).search(/[\s/>]/) + i
    const tag = src.slice(i, tagEnd)
    i = tagEnd
    const attrs: Record<string, string> = {}
    for (;;) {
      ws()
      if (src[i] === '/' && src[i + 1] === '>') {
        i += 2
        return { tag, attrs, children: [], text: '' }
      }
      if (src[i] === '>') {
        i++
        break
      }
      const m = /^([\w:-]+)\s*=\s*"([^"]*)"/.exec(src.slice(i))
      if (!m) throw new Error(`bad attribute at ${i}`)
      attrs[m[1]] = unesc(m[2])
      i += m[0].length
    }
    const children: XNode[] = []
    let text = ''
    while (!src.startsWith(`</${tag}`, i)) {
      if (i >= src.length) throw new Error('unterminated element')
      if (src[i] === '<') children.push(node())
      else text += src[i++]
    }
    i = src.indexOf('>', i) + 1
    return { tag, attrs, children, text: unesc(text) }
  }
  return node()
}

function fromXmlNode(n: XNode): unknown {
  switch (n.attrs.t) {
    case 'null':
      return null
    case 'bool':
      return n.text === 'true' || n.text === 'True'
    case 'int':
      return parseInt(n.text, 10)
    case 'float':
      return parseFloat(n.text)
    case 'str':
      return n.text
    case 'list':
      return n.children.map(fromXmlNode)
    case 'dict': {
      const o: Record<string, unknown> = {}
      for (const e of n.children) o[e.attrs.key] = fromXmlNode(e.children[0])
      return o
    }
    default:
      throw new Error(`unknown XML type ${n.attrs.t}`)
  }
}

export function marshal(obj: unknown, fmt: WireFormat = 'json'): string {
  return fmt === 'xml' ? `<message>${toXml('envelope', obj)}</message>` : JSON.stringify(obj)
}

export function unmarshal<T = Envelope>(text: string, fmt: WireFormat = 'json'): T {
  if (fmt === 'xml') {
    const root = parseXml(text)
    const env = root.children.find((c) => c.tag === 'envelope')
    if (!env) throw new Error('missing <envelope>')
    return fromXmlNode(env) as T
  }
  return JSON.parse(text) as T
}

export const formatFromContentType = (ct: string | null | undefined): WireFormat =>
  /xml/i.test(ct || '') ? 'xml' : 'json'
