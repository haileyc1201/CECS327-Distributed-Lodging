/**
 * Property Service — D1 reads/writes for properties table.
 * Mirrors Node Express property-service behavior.
 */
import { appendLog } from '../logger'
import type { Property } from '../types'

/** Seed availability used by hard reset (102, 107, 112 unavailable). */
export const SEED_AVAILABILITY: Record<number, number> = {
  101: 1,
  102: 0,
  103: 1,
  104: 1,
  105: 1,
  106: 1,
  107: 0,
  108: 1,
  109: 1,
  110: 1,
  111: 1,
  112: 0,
}

type PropertyRow = {
  id: number
  name: string
  price: number
  available: number
  city: string | null
  beds: number | null
}

function rowToProperty(row: PropertyRow): Property {
  return {
    id: row.id,
    name: row.name,
    price: row.price,
    available: Boolean(row.available),
    city: row.city || '',
    beds: row.beds ?? 1,
  }
}

function log(message: string) {
  appendLog('property', message)
}

export async function listProperties(db: D1Database): Promise<Property[]> {
  const { results } = await db
    .prepare(
      'SELECT id, name, price, available, city, beds FROM properties ORDER BY id',
    )
    .all<PropertyRow>()
  const properties = (results || []).map(rowToProperty)
  log(`list_properties -> ${properties.length} items`)
  return properties
}

export async function findProperty(
  db: D1Database,
  propertyId: number | string,
): Promise<Property | null> {
  const row = await db
    .prepare(
      'SELECT id, name, price, available, city, beds FROM properties WHERE id = ?',
    )
    .bind(Number(propertyId))
    .first<PropertyRow>()
  if (!row) return null
  log(`get_property ${propertyId}`)
  return rowToProperty(row)
}

export async function setPropertyAvailable(
  db: D1Database,
  propertyId: number | string,
  available: boolean,
): Promise<Property | null> {
  const existing = await findProperty(db, propertyId)
  if (!existing) return null
  await db
    .prepare('UPDATE properties SET available = ? WHERE id = ?')
    .bind(available ? 1 : 0, Number(propertyId))
    .run()
  log(`set availability property ${propertyId} -> ${available}`)
  return findProperty(db, propertyId)
}

export async function resetSeedAvailability(db: D1Database): Promise<void> {
  const stmt = db.prepare('UPDATE properties SET available = ? WHERE id = ?')
  const batch = Object.entries(SEED_AVAILABILITY).map(([id, available]) =>
    stmt.bind(available, Number(id)),
  )
  if (batch.length > 0) {
    await db.batch(batch)
  }
  log('reset seed availability (102,107,112 unavailable)')
}
