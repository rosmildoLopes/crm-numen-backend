# Academia Numen — CRM Backend (MVP funcional)

## Arranque local (Python 3.12+)

```bash
cp .env.example .env
# Cambiar JWT_SECRET y ADMIN_PASSWORD en .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API: http://localhost:8000/docs · Health: http://localhost:8000/health

La base de datos local predeterminada es SQLite para facilitar pruebas. Para PostgreSQL utilizar `docker compose up --build` (configurar `.env` antes). El backend crea el superadmin al primer inicio con las credenciales de `.env`.

### Incluido
- Login JWT, usuarios y roles predefinidos, permisos aplicados en backend.
- Cursos comerciales, leads, asignación, estados, notas, auditoría, dashboard.
- Ventas y confirmación **manual** de pago; bandeja `outbox` de eventos pendientes.
- Documentación OpenAPI en `/docs`.

### Aún NO implementado
- Envío real de email/WhatsApp (outbox registra eventos, no los envía).
- IA, automatización de 12 horas, webhooks de formularios, exportaciones, facturación.
- Matrícula real en Campus, verificación de pagos con proveedor, SSO.
- Permisos configurables dinámicamente, migraciones Alembic, paginación avanzada, tests de integración completos.

**No desplegar como producción sin** HTTPS, gestión de secretos, migraciones, backups, protección antiabuso, autenticación reforzada, permisos revisados y pruebas de seguridad. No usar datos personales reales durante las primeras pruebas.
