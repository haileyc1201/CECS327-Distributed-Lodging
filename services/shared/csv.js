/**
 * Shared CSV helpers for properties.csv and reservations.csv
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const DATA_DIR = path.join(ROOT, 'data');
const LOGS_DIR = path.join(ROOT, 'logs');

const PROPERTIES_FILE = path.join(DATA_DIR, 'properties.csv');
const RESERVATIONS_FILE = path.join(DATA_DIR, 'reservations.csv');

const PROPERTY_FIELDS = ['id', 'name', 'price', 'available', 'city', 'beds'];
const RESERVATION_FIELDS = [
  'reservation_id',
  'property_id',
  'property_name',
  'guest_name',
  'amount',
  'payment_id',
  'refund_id',
  'status',
  'created_at',
  'cancelled_at',
];

const SEED_PROPERTIES = [
  { id: '101', name: 'Long Beach Apartment', price: '150', available: 'true', city: 'Long Beach', beds: '2' },
  { id: '102', name: 'Downtown Studio', price: '120', available: 'false', city: 'Long Beach', beds: '1' },
  { id: '103', name: 'Beach House', price: '275', available: 'true', city: 'Long Beach', beds: '3' },
  { id: '104', name: 'Belmont Shore Loft', price: '195', available: 'true', city: 'Long Beach', beds: '2' },
  { id: '105', name: 'Campus Cottage', price: '110', available: 'true', city: 'Long Beach', beds: '1' },
  { id: '106', name: 'Harbor View Condo', price: '230', available: 'true', city: 'Long Beach', beds: '2' },
  { id: '107', name: 'Naples Canal Home', price: '340', available: 'false', city: 'Long Beach', beds: '4' },
  { id: '108', name: 'Signal Hill Bungalow', price: '165', available: 'true', city: 'Signal Hill', beds: '2' },
  { id: '109', name: 'Seal Beach Cabin', price: '210', available: 'true', city: 'Seal Beach', beds: '2' },
  { id: '110', name: 'Arts District Flat', price: '180', available: 'true', city: 'Los Angeles', beds: '1' },
  { id: '111', name: 'Koreatown Suite', price: '140', available: 'true', city: 'Los Angeles', beds: '1' },
  { id: '112', name: 'Pasadena Guest House', price: '255', available: 'false', city: 'Pasadena', beds: '3' },
];

function parseBool(value) {
  if (typeof value === 'boolean') return value;
  return String(value).trim().toLowerCase() === 'true' ||
    String(value).trim() === '1' ||
    String(value).trim().toLowerCase() === 'yes';
}

function escapeCsvField(value) {
  const s = value == null ? '' : String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function parseCsvLine(line) {
  const fields = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        current += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ',') {
      fields.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

function readCsv(filePath) {
  if (!fs.existsSync(filePath)) {
    return { headers: [], rows: [] };
  }
  const text = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== '');
  if (lines.length === 0) return { headers: [], rows: [] };
  const headers = parseCsvLine(lines[0]);
  const rows = lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const obj = {};
    headers.forEach((h, i) => {
      obj[h] = values[i] !== undefined ? values[i] : '';
    });
    return obj;
  });
  return { headers, rows };
}

function writeCsv(filePath, headers, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const lines = [headers.join(',')];
  for (const row of rows) {
    lines.push(headers.map((h) => escapeCsvField(row[h])).join(','));
  }
  fs.writeFileSync(filePath, `${lines.join('\n')}\n`, 'utf8');
}

function loadProperties() {
  const { rows } = readCsv(PROPERTIES_FILE);
  return rows.map((row) => ({
    id: parseInt(row.id, 10),
    name: row.name,
    price: parseInt(Number(row.price), 10),
    available: parseBool(row.available),
    city: row.city || '',
    beds: row.beds !== undefined && row.beds !== '' ? parseInt(row.beds, 10) : 1,
  }));
}

function findProperty(propertyId) {
  return loadProperties().find((p) => p.id === Number(propertyId)) || null;
}

function setPropertyAvailable(propertyId, available) {
  const { headers, rows } = readCsv(PROPERTIES_FILE);
  const fieldnames = headers.length ? headers : PROPERTY_FIELDS;
  let found = false;
  for (const row of rows) {
    if (parseInt(row.id, 10) === Number(propertyId)) {
      row.available = available ? 'true' : 'false';
      found = true;
    }
  }
  if (!found) return false;
  writeCsv(PROPERTIES_FILE, fieldnames, rows);
  return true;
}

function ensureReservationsFile() {
  if (!fs.existsSync(RESERVATIONS_FILE) || fs.statSync(RESERVATIONS_FILE).size === 0) {
    writeCsv(RESERVATIONS_FILE, RESERVATION_FIELDS, []);
  }
}

function loadReservations() {
  ensureReservationsFile();
  const { rows } = readCsv(RESERVATIONS_FILE);
  return rows
    .filter((row) => row.reservation_id)
    .map((row) => ({
      reservation_id: row.reservation_id,
      property_id: row.property_id ? parseInt(row.property_id, 10) : null,
      property_name: row.property_name || '',
      guest_name: row.guest_name || '',
      amount: row.amount ? parseInt(Number(row.amount), 10) : 0,
      payment_id: row.payment_id || null,
      refund_id: row.refund_id || null,
      status: row.status || 'confirmed',
      created_at: row.created_at || null,
      cancelled_at: row.cancelled_at || null,
    }));
}

function saveReservations(reservations) {
  const rows = reservations.map((res) => ({
    reservation_id: res.reservation_id || '',
    property_id: res.property_id ?? '',
    property_name: res.property_name || '',
    guest_name: res.guest_name || '',
    amount: res.amount ?? '',
    payment_id: res.payment_id || '',
    refund_id: res.refund_id || '',
    status: res.status || 'confirmed',
    created_at: res.created_at || '',
    cancelled_at: res.cancelled_at || '',
  }));
  writeCsv(RESERVATIONS_FILE, RESERVATION_FIELDS, rows);
}

function resetDemoData() {
  writeCsv(PROPERTIES_FILE, PROPERTY_FIELDS, SEED_PROPERTIES);
  writeCsv(RESERVATIONS_FILE, RESERVATION_FIELDS, []);
}

function appendLog(serviceName, message) {
  try {
    fs.mkdirSync(LOGS_DIR, { recursive: true });
    const logFile = path.join(LOGS_DIR, `${serviceName}.log`);
    const entry = JSON.stringify({ ts: new Date().toISOString(), message }) + '\n';
    fs.appendFileSync(logFile, entry, 'utf8');
  } catch {
    // ignore log errors
  }
}

function readRecentLogs(maxLines = 100) {
  const lines = [];
  if (!fs.existsSync(LOGS_DIR)) return lines;
  const files = fs.readdirSync(LOGS_DIR).filter((f) => f.endsWith('.log')).sort();
  for (const file of files) {
    try {
      const content = fs.readFileSync(path.join(LOGS_DIR, file), 'utf8').trim();
      if (!content) continue;
      const fileLines = content.split(/\r?\n/).slice(-30);
      for (const line of fileLines) {
        lines.push({ file, line });
      }
    } catch {
      // skip
    }
  }
  return lines.slice(-maxLines);
}

module.exports = {
  ROOT,
  DATA_DIR,
  LOGS_DIR,
  PROPERTIES_FILE,
  RESERVATIONS_FILE,
  PROPERTY_FIELDS,
  RESERVATION_FIELDS,
  SEED_PROPERTIES,
  loadProperties,
  findProperty,
  setPropertyAvailable,
  loadReservations,
  saveReservations,
  resetDemoData,
  appendLog,
  readRecentLogs,
};
