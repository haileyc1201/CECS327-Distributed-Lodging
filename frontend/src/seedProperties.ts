/** Seed listings mirrored from data/properties.csv for GitHub Pages demo mode. */
export type SeedProperty = {
  id: number
  name: string
  price: number
  available: boolean
  city: string
  beds: number
}

export const SEED_PROPERTIES: SeedProperty[] = [
  { id: 101, name: 'Long Beach Apartment', price: 150, available: true, city: 'Long Beach', beds: 2 },
  { id: 102, name: 'Downtown Studio', price: 120, available: false, city: 'Long Beach', beds: 1 },
  { id: 103, name: 'Beach House', price: 275, available: true, city: 'Long Beach', beds: 3 },
  { id: 104, name: 'Belmont Shore Loft', price: 195, available: true, city: 'Long Beach', beds: 2 },
  { id: 105, name: 'Campus Cottage', price: 110, available: true, city: 'Long Beach', beds: 1 },
  { id: 106, name: 'Harbor View Condo', price: 230, available: true, city: 'Long Beach', beds: 2 },
  { id: 107, name: 'Naples Canal Home', price: 340, available: false, city: 'Long Beach', beds: 4 },
  { id: 108, name: 'Signal Hill Bungalow', price: 165, available: true, city: 'Signal Hill', beds: 2 },
  { id: 109, name: 'Seal Beach Cabin', price: 210, available: true, city: 'Seal Beach', beds: 2 },
  { id: 110, name: 'Arts District Flat', price: 180, available: true, city: 'Los Angeles', beds: 1 },
  { id: 111, name: 'Koreatown Suite', price: 140, available: true, city: 'Los Angeles', beds: 1 },
  { id: 112, name: 'Pasadena Guest House', price: 255, available: false, city: 'Pasadena', beds: 3 },
]

export function cloneSeedProperties(): SeedProperty[] {
  return SEED_PROPERTIES.map((p) => ({ ...p }))
}
