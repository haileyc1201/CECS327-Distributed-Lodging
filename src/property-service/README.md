# Property Service

Property information and availability over TCP JSON on `127.0.0.1:5001`.

## Run

```bash
python src/property-service/property_service.py
```

## Actions

- `get_property` — `{ "action": "get_property", "property_id": 101 }`
- `list_properties` — `{ "action": "list_properties" }`
- Backward compatible: `{ "property_id": 101 }` behaves like `get_property`

Data file: `data/properties.json`
