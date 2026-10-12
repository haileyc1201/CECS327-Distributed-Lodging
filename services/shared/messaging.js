/**
 * Messaging layer shared by every Node service.
 *
 *  - Envelope format (same as the Python simulation on `main`):
 *      { id, type, sender, receiver, timestamp, correlation_id, payload }
 *  - Marshalling / unmarshalling to JSON (application/json) or a typed XML
 *    mapping (application/xml).
 *  - ISO-8601 timestamped logging of every SEND / RECV into logs/messages.jsonl,
 *    recording the message before marshalling and the wire text after it.
 *  - sendMessage(): HTTP request-reply that marshals, logs, sends, receives,
 *    unmarshals and logs the reply.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..', '..');
const LOG_FILE = process.env.COMM_LOG_FILE || path.join(ROOT, 'logs', 'messages.jsonl');
const QUIET = !!process.env.COMM_QUIET;
const CONTENT_TYPES = { json: 'application/json', xml: 'application/xml' };

const nowIso = () => new Date().toISOString();

function makeEnvelope(type, sender, payload, { receiver = null, correlationId = null } = {}) {
  return {
    id: crypto.randomBytes(6).toString('hex'),
    type,
    sender,
    receiver,
    timestamp: nowIso(),
    correlation_id: correlationId,
    payload,
  };
}

// ------------------------------------------------------------------ XML
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&');

function toXml(tag, v, attrs = '') {
  if (v === null || v === undefined) return `<${tag}${attrs} t="null"/>`;
  if (typeof v === 'boolean') return `<${tag}${attrs} t="bool">${v}</${tag}>`;
  if (typeof v === 'number') return `<${tag}${attrs} t="${Number.isInteger(v) ? 'int' : 'float'}">${v}</${tag}>`;
  if (typeof v === 'string') return `<${tag}${attrs} t="str">${esc(v)}</${tag}>`;
  if (Array.isArray(v)) return `<${tag}${attrs} t="list">${v.map((x) => toXml('item', x)).join('')}</${tag}>`;
  return `<${tag}${attrs} t="dict">${Object.entries(v)
    .map(([k, x]) => `<entry key="${esc(k)}">${toXml('value', x)}</entry>`)
    .join('')}</${tag}>`;
}

/** Minimal parser for the XML produced by toXml (also produced by the Python codec). */
function parseXml(src) {
  let i = 0;
  const ws = () => { while (/\s/.test(src[i])) i++; };
  function node() {
    ws();
    if (src.startsWith('<?', i)) { i = src.indexOf('?>', i) + 2; ws(); }
    if (src[i] !== '<') throw new Error(`XML parse error at ${i}`);
    i++;
    const tagEnd = src.slice(i).search(/[\s/>]/) + i;
    const tag = src.slice(i, tagEnd);
    i = tagEnd;
    const attrs = {};
    for (;;) {
      ws();
      if (src[i] === '/' && src[i + 1] === '>') { i += 2; return { tag, attrs, children: [], text: '' }; }
      if (src[i] === '>') { i++; break; }
      const m = /^([\w:-]+)\s*=\s*"([^"]*)"/.exec(src.slice(i));
      if (!m) throw new Error(`bad attribute at ${i}`);
      attrs[m[1]] = unesc(m[2]);
      i += m[0].length;
    }
    const children = [];
    let text = '';
    while (!src.startsWith(`</${tag}`, i)) {
      if (src[i] === '<') children.push(node());
      else { text += src[i]; i++; }
      if (i >= src.length) throw new Error('unterminated element');
    }
    i = src.indexOf('>', i) + 1;
    return { tag, attrs, children, text: unesc(text) };
  }
  return node();
}

function fromXmlNode(n) {
  switch (n.attrs.t) {
    case 'null': return null;
    case 'bool': return n.text === 'true' || n.text === 'True';
    case 'int': return parseInt(n.text, 10);
    case 'float': return parseFloat(n.text);
    case 'str': return n.text;
    case 'list': return n.children.map(fromXmlNode);
    case 'dict': {
      const o = {};
      for (const e of n.children) o[e.attrs.key] = fromXmlNode(e.children[0]);
      return o;
    }
    default: throw new Error(`unknown XML type ${n.attrs.t}`);
  }
}

function marshal(obj, fmt = 'json') {
  if (fmt === 'json') return JSON.stringify(obj);
  if (fmt === 'xml') return `<message>${toXml('envelope', obj)}</message>`;
  throw new Error(`unsupported format ${fmt}`);
}

function unmarshal(text, fmt = 'json') {
  if (fmt === 'json') return JSON.parse(text);
  if (fmt === 'xml') {
    const root = parseXml(text);
    return fromXmlNode(root.children.find((c) => c.tag === 'envelope'));
  }
  throw new Error(`unsupported format ${fmt}`);
}

const formatFromContentType = (ct = '') => (/xml/i.test(ct) ? 'xml' : 'json');

// ------------------------------------------------------------------ logging
function writeLog(entry) {
  try {
    fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true });
    fs.appendFileSync(LOG_FILE, JSON.stringify(entry) + '\n', 'utf8');
  } catch {
    /* ignore */
  }
  if (!QUIET) {
    const m = entry.message || {};
    const arrow = entry.event === 'SEND' ? '->' : entry.event === 'RECV' ? '<-' : '**';
    console.log(`${entry.ts} [${entry.node}] ${entry.event.padEnd(5)} ${arrow} ${entry.peer || ''} type=${m.type || ''} id=${m.id || ''} fmt=${entry.format || ''} bytes=${entry.bytes ?? ''} ${entry.note || ''}`);
  }
}

function makeLogger(node) {
  return {
    send(peer, message, wire, fmt) {
      writeLog({ ts: nowIso(), node, event: 'SEND', peer, format: fmt, bytes: Buffer.byteLength(wire), message, wire });
    },
    recv(peer, wire, message, fmt) {
      writeLog({ ts: nowIso(), node, event: 'RECV', peer, format: fmt, bytes: Buffer.byteLength(wire), wire, message });
    },
    info(note, extra = {}) {
      writeLog({ ts: nowIso(), node, event: 'INFO', note, ...extra });
    },
  };
}

/** HTTP request-reply with an envelope. Returns the unmarshalled reply envelope. */
async function sendMessage(logger, url, envelope, fmt = 'json', timeoutMs = 4000) {
  const wire = marshal(envelope, fmt);
  logger.send(url, envelope, wire, fmt);
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': CONTENT_TYPES[fmt], Accept: CONTENT_TYPES[fmt] },
    body: wire,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  const rfmt = formatFromContentType(res.headers.get('content-type'));
  const reply = unmarshal(text, rfmt);
  logger.recv(url, text, reply, rfmt);
  return reply;
}

/** Express middleware: read the raw body, unmarshal it, log RECV, expose req.envelope. */
function envelopeBody(logger) {
  return (req, res, next) => {
    let raw = '';
    req.setEncoding('utf8');
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      const fmt = formatFromContentType(req.headers['content-type']);
      try {
        req.envelope = unmarshal(raw, fmt);
        req.wireFormat = fmt;
        logger.recv(`${req.socket.remoteAddress}:${req.socket.remotePort}`, raw, req.envelope, fmt);
        next();
      } catch (err) {
        res.status(400).json({ status: 'error', message: `unmarshal failed: ${err.message}` });
      }
    });
  };
}

/** Reply with an envelope in the same format the request used, logging SEND. */
function replyEnvelope(logger, req, res, envelope, httpStatus = 200) {
  const fmt = req.wireFormat || 'json';
  const wire = marshal(envelope, fmt);
  logger.send(`${req.socket.remoteAddress}:${req.socket.remotePort}`, envelope, wire, fmt);
  res.status(httpStatus).type(CONTENT_TYPES[fmt]).send(wire);
}

function readMessageLog(limit = 200) {
  if (!fs.existsSync(LOG_FILE)) return [];
  const lines = fs.readFileSync(LOG_FILE, 'utf8').trim().split(/\n/).filter(Boolean);
  return lines.slice(-limit).map((l) => JSON.parse(l));
}

module.exports = {
  LOG_FILE,
  CONTENT_TYPES,
  nowIso,
  makeEnvelope,
  marshal,
  unmarshal,
  formatFromContentType,
  makeLogger,
  sendMessage,
  envelopeBody,
  replyEnvelope,
  readMessageLog,
};
