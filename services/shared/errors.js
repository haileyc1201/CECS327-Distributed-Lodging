/**
 * Error masking helper (Node services).
 * Unexpected errors are logged in full on the server with a short reference ID;
 * the client only gets a generic message plus that ID. Validation errors
 * (400/404 with a clear message) are sent directly by the routes, not through here.
 */
const crypto = require('crypto');

const GENERIC_MESSAGE = 'Something went wrong. Please try again.';

function makeRef() {
  return crypto.randomBytes(4).toString('hex');
}

function describe(err) {
  if (err instanceof Error) return err.stack || err.message;
  return typeof err === 'string' ? err : JSON.stringify(err);
}

/** Log the real error and return the safe body the client sees. */
function maskError(log, context, err, ref = makeRef()) {
  log(`${context} [ref ${ref}]: ${describe(err)}`);
  return { status: 'error', message: GENERIC_MESSAGE, ref };
}

/** Express shortcut: log + respond, keeping the original HTTP status. */
function sendError(res, log, context, err, status = 500) {
  return res.status(status).json(maskError(log, context, err));
}

/** Gateway: sanitize a downstream 5xx JSON body before passing it on. */
function sanitizeDownstream(httpStatus, data, log, context) {
  if (httpStatus < 500) return data;
  const ref = (data && typeof data.ref === 'string' && data.ref) || makeRef();
  log(`${context} downstream ${httpStatus} [ref ${ref}]: ${describe(data)}`);
  return { status: 'error', message: GENERIC_MESSAGE, ref };
}

/** JSON-RPC: intentional RpcErrors (with a code) pass through, anything else is masked. */
function rpcError(log, context, err) {
  if (err && err.name === 'RpcError' && Number.isInteger(err.code)) {
    return { code: err.code, message: err.message, data: err.data };
  }
  const ref = makeRef();
  log(`${context} [ref ${ref}]: ${describe(err)}`);
  return { code: -32603, message: GENERIC_MESSAGE, data: { ref } };
}

module.exports = { GENERIC_MESSAGE, makeRef, maskError, sendError, sanitizeDownstream, rpcError };
