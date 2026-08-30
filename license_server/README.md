# ConvertManager License Server

This is the separate Flask API for commercial license validation. The server,
not the desktop client, is authoritative for commercial license state.

## Local setup

```bash
python -m pip install -r license_server/requirements.txt
copy license_server/.env.example license_server/.env
python -m license_server.app
```

For local development, `.env` can use SQLite. Production should set
`DATABASE_URL` to a MySQL URL or provide `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, and `DB_PASSWORD`. Never commit `.env` or real credentials.

## API

- `POST /api/license/activate`
- `POST /api/license/validate`
- `POST /api/license/deactivate`
- `GET` or `POST /api/license/info`
- Protected admin endpoints under `/api/license/admin/licenses`

Admin endpoints support creating, listing, viewing, revoking, reactivating,
updating expiration/max devices, and deactivating a device. They require the
server-only `X-Admin-Token` header.

Client requests require `license_key` and `device_id`. Admin requests require
the `X-Admin-Token` header configured only on the server.

The development server is HTTP-only for local use. Production deployment must
place Flask behind an HTTPS reverse proxy, use a strong `SECRET_KEY`, a real
admin identity system, a managed MySQL database, and operational monitoring.