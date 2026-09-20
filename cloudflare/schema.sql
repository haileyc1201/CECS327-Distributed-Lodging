-- D1 schema for cecs327-lodging (already applied in Tom's Cloudflare account)
CREATE TABLE IF NOT EXISTS properties (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  price INTEGER NOT NULL,
  available INTEGER NOT NULL,
  city TEXT,
  beds INTEGER
);

CREATE TABLE IF NOT EXISTS reservations (
  reservation_id TEXT PRIMARY KEY,
  property_id INTEGER NOT NULL,
  property_name TEXT,
  guest_name TEXT,
  amount REAL,
  payment_id TEXT,
  refund_id TEXT,
  status TEXT,
  created_at TEXT,
  cancelled_at TEXT
);

-- Seed availability: 102, 107, 112 unavailable; others available
INSERT OR REPLACE INTO properties (id, name, price, available, city, beds) VALUES
  (101, 'Long Beach Apartment', 150, 1, 'Long Beach', 2),
  (102, 'Downtown Studio', 120, 0, 'Long Beach', 1),
  (103, 'Beach House', 275, 1, 'Long Beach', 3),
  (104, 'Belmont Shore Loft', 195, 1, 'Long Beach', 2),
  (105, 'Campus Cottage', 110, 1, 'Long Beach', 1),
  (106, 'Harbor View Condo', 230, 1, 'Long Beach', 2),
  (107, 'Naples Canal Home', 340, 0, 'Long Beach', 4),
  (108, 'Signal Hill Bungalow', 165, 1, 'Signal Hill', 2),
  (109, 'Seal Beach Cabin', 210, 1, 'Seal Beach', 2),
  (110, 'Arts District Flat', 180, 1, 'Los Angeles', 1),
  (111, 'Koreatown Suite', 140, 1, 'Los Angeles', 1),
  (112, 'Pasadena Guest House', 255, 0, 'Pasadena', 3);
