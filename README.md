# Academia Numen CRM V6

Secuencias de seguimiento, preferencias de email, baja pública y reprogramación de tareas, sobre la V5 existente.

- [Actualizar sin reemplazar .env, SQLite ni Git](INSTALACION-V6.md)
- [Cambios V6](CHANGELOG-V6.md)
- [Pruebas ejecutadas y límites](PRUEBAS-V6.md)

Los documentos V5 se conservan como referencia histórica; para esta entrega usar los archivos V6.

Backend: Python 3.12. `python -m pip install -r requirements.txt`, `python -m pytest -q`. Para una primera prueba sin envíos ni trabajador periódico: `EMAIL_DELIVERY_ENABLED=false AUTOMATION_ENABLED=false python -m uvicorn app.main:app --reload`.

Frontend: Node 22 recomendado. `npm ci`, `npm run typecheck`, `npm test`, `npm run build`; desarrollo con `npm run dev`.

Agregar PUBLIC_CRM_URL=http://localhost:3000 al .env del backend para activar y probar secuencias locales. Usar una URL pública del frontend antes de enviarlas a personas fuera de tu computadora. Las secuencias no inscriben leads automáticamente al instalar.

SMTP e IA reales requieren configuración y validación con el proveedor. No se conectó el campus ni se modificó la instalación original de Work.
