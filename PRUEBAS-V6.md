# Verificación de Academia Numen CRM V6

Fecha: 20 de noviembre de 2026.

## Resultado final

- Backend: **52 pruebas aprobadas**, ejecutadas mediante `python -m pytest -q` desde back. Incluyen las 28 heredadas de V5 y 24 casos nuevos de V6. Una advertencia de deprecación de Starlette/AnyIO; no hubo errores en la ejecución final.
- Frontend: **2 pruebas aprobadas** de permisos, revisión de TypeScript sin errores y compilación de producción Next.js completada con 23 páginas estáticas contando rutas internas.
- Navegador: comprobación interactiva de las nuevas pantallas con base SQLite temporal y SMTP/IA desactivados.
- ZIP: inspección de contenido requerido e integridad CRC, sin archivos .env reales, bases del usuario ni dependencias instaladas.

## Casos cubiertos por V6

- Preferencias inicialmente desconocidas y constancia obligatoria para autorizar.
- Validación de contenido, variables, cantidad de pasos, demoras y saltos de asunto.
- Vista previa sin crear tokens ni mensajes.
- Permisos de administración y acceso del vendedor a su cartera.
- Rechazo de inscripción sin autorización, con bloqueo o estado comercial incompatible.
- Una sola secuencia en curso por email y prevención de la repetición del mismo lead/secuencia.
- Creación única de cada paso al repetir ejecuciones.
- Esperas desde la aceptación real del paso anterior por SMTP simulado.
- Pausa que retiene mensajes y reanudación sin duplicar el envío.
- Detención por respuesta registrada, cambio de estado, cambio de email, compra confirmada, baja y acción manual.
- Registro sin respuesta y asignación de vendedor no interrumpen por sí mismos una secuencia.
- Baja pública por POST, confirmación idempotente, tokens inválidos/vencidos y almacenamiento del hash.
- Preferencias compartidas por email, bloqueo de mensajes heredados y bienvenida de un lead posterior, conservando el evento Campus.
- Revisión de preferencias antes de SMTP, entrega incierta y reintento manual.
- Pasos protegidos cuando ya existen participantes; activación rechazada si falta URL para baja.
- No reiniciar el email único V5 después de completar una secuencia.
- Reprogramación con zona horaria, nuevo aviso de vencimiento sin repetición y autorización de acceso.
- Creación de tablas V6 sobre un esquema V5 con datos de prueba, conservando el lead existente.

## Recorrido observado en el navegador

Se ingresó como administrador de una base de prueba; se creó un lead ficticio, una secuencia de dos pasos y su vista previa personalizada. Se activó la secuencia, se guardó una autorización ficticia y se inscribió el lead. Una ejecución manual generó el primer paso en cola sin enviarlo. Se abrió el enlace de baja del mensaje, se confirmó y se verificaron autorización retirada, bloqueo, participación detenida y paso cancelado. Captura: VERIFICACION-UI-V6.jpg.

La reprogramación de tareas se validó mediante API y pruebas automatizadas, no con un recorrido adicional de navegador. Las últimas correcciones del backend (supresión de bienvenidas para direcciones bloqueadas y prevención del reinicio del seguimiento V5) se verificaron en la suite final completa.

## Entorno y límites

Se utilizaron Python y dependencias ya instaladas en los proyectos de Work, junto con un enlace local a node_modules para compilar. Los proyectos originales no se editaron. El enlace y las compilaciones no están incluidos en los ZIP. No se probó una instalación limpia de dependencias.

Los tests fuerzan SQLite temporal y deshabilitan servicios externos. Las pruebas SMTP son simuladas: no se envió correo real ni se comprobó recepción en buzón. No se realizaron llamadas reales a IA, pruebas de Docker/PostgreSQL, carga distribuida, despliegue público, campus, WhatsApp ni pagos de proveedor. Las comprobaciones del navegador fueron interactivas; las dos pruebas del frontend no constituyen una suite completa de interfaz.

Para reproducir: backend con `python -m pytest -q`; frontend con `npm run typecheck`, `npm test` y `npm run build` después de instalar dependencias.
