/**
 * Property Service — Express HTTP on :5001
 * GET /properties, GET /properties/:id, PATCH /properties/:id/availability
 */
const express = require('express');
const {
  loadProperties,
  findProperty,
  setPropertyAvailable,
  appendLog,
} = require('../shared/csv');

const HOST = process.env.PROPERTY_HOST || '127.0.0.1';
const PORT = Number(process.env.PROPERTY_PORT || 5001);

const app = express();
app.use(express.json());

function log(message) {
  console.log(`[PROPERTY] ${message}`);
  appendLog('property', message);
}

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: 'property' });
});

app.get('/properties', (_req, res) => {
  try {
    const properties = loadProperties();
    log(`list_properties -> ${properties.length} items`);
    res.json({ status: 'success', properties });
  } catch (err) {
    log(`list error: ${err.message}`);
    res.status(500).json({ status: 'error', message: err.message });
  }
});

app.get('/properties/:id', (req, res) => {
  try {
    const property = findProperty(req.params.id);
    if (!property) {
      return res.status(404).json({ status: 'error', message: 'Property not found' });
    }
    log(`get_property ${req.params.id}`);
    return res.json({ status: 'success', property });
  } catch (err) {
    log(`get error: ${err.message}`);
    return res.status(500).json({ status: 'error', message: err.message });
  }
});

app.patch('/properties/:id/availability', (req, res) => {
  try {
    const available = req.body?.available;
    if (typeof available !== 'boolean') {
      return res.status(400).json({ status: 'error', message: 'available (boolean) is required' });
    }
    const ok = setPropertyAvailable(req.params.id, available);
    if (!ok) {
      return res.status(404).json({ status: 'error', message: 'Property not found' });
    }
    log(`set availability property ${req.params.id} -> ${available}`);
    const property = findProperty(req.params.id);
    return res.json({ status: 'success', property });
  } catch (err) {
    log(`availability error: ${err.message}`);
    return res.status(500).json({ status: 'error', message: err.message });
  }
});

app.listen(PORT, HOST, () => {
  log(`Listening on http://${HOST}:${PORT}`);
});
