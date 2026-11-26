# Academia Numen CRM V5

Entrega: 13 de noviembre de 2026. Parte de la V4 entregada en este chat. Los proyectos de `~/Work` y sus datos no fueron modificados. Los ZIP son proyectos completos, no parches.

## Gestión comercial local

- **Tareas y agenda:** crear próximo contacto, responsable, detalle, fecha y hora; filtrar pendientes, vencidas, completadas y canceladas; completar, cancelar y reabrir.
- **Recordatorios:** las tareas pendientes vencidas generan una notificación por tarea. El trabajador periódico debe estar encendido. La notificación no se repite al reabrir una tarea ya notificada.
- **Reasignación:** las tareas pendientes de un lead se trasladan a su nuevo vendedor; las tareas completadas conservan su responsable histórico.
- **Contactos:** registro de canal, resultado, detalle y autor; historial por interesado. Es un registro de conversaciones realizadas, no una conexión real con WhatsApp ni lectura del buzón.
- **Detención de seguimiento:** al registrar una respuesta, un cambio a contactado/pensando/cerrado, una asignación o una compra confirmada, se cancela el email de seguimiento que aún esté en cola. No se puede retirar un email ya aceptado por SMTP.
- **Importar CSV:** vista previa, hasta 1000 filas y 1 MB de texto; informa filas inválidas y repetidas. La confirmación crea únicamente las válidas. Revalida contra la base al confirmar. No actualiza registros existentes ni envía emails de bienvenida.
- **Duplicados:** comparación de email sin espacios en extremos y sin distinguir mayúsculas. Muestra todos los leads repetidos; no elimina ni fusiona información. No detecta teléfonos equivalentes ni personas con emails diferentes.
- **Asignación por carga:** distribuye leads abiertos sin vendedor entre vendedores activos. Prioriza consulta más antigua, menor cantidad de leads abiertos y, en empate, menor ID. Disponible manualmente y de forma periódica opcional. No cambia leads ya asignados.
- **Reglas comerciales:** umbral de 1 a 720 horas, activar/desactivar email de seguimiento, activar/desactivar asignación automática. Predeterminados: 12 horas, email de seguimiento activo en cola y reparto automático desactivado.
- **Métricas:** agrupación por vendedor actual, curso de interés y origen; cantidad de leads, conversión y ventas confirmadas. Importes separados por moneda y ocultos a roles sin permiso de ventas. El vendedor ve su cartera actual.
- **Acceso heredado:** se admite el identificador administrativo local admin@numen.local en el inicio de sesión.
- **Fechas:** salida UTC explícita para registros y tareas; fechas de tareas normalizadas al recibir su zona horaria. El navegador las presenta en su zona local.

## Primera integración de IA

- Asistente comercial opcional: analiza el texto introducido por el usuario, estado y datos del curso y propone resumen, respuesta y próximo paso.
- Texto editable y guardado como nota revisada. La IA no envía mensajes, no asigna leads, no confirma pagos ni matricula.
- Integración HTTP con OpenAI Responses y formato JSON estructurado validado en el backend; sin herramientas de ejecución.
- Configuración únicamente en el backend; sin clave en el frontend. Desactivado por defecto y modelo sin preseleccionar.
- Confirmación explícita en la pantalla antes de compartir texto y contexto. No se envían automáticamente nombre, email, teléfono ni notas del lead. El texto pegado y la descripción del curso pueden contener información: revisarlos antes de compartir.
- Límite configurable de solicitudes por usuario por día UTC y límite de salida por solicitud. No es un límite de gasto monetario. Los intentos que fallen tras reservar cupo también consumen una solicitud.
- Registro de borrador, usuario, modelo y actividad. No hay una bandeja histórica de borradores: el resultado se puede conservar como nota.

Referencia de implementación: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) y [Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses). Se solicita `store:false`; esto no equivale a una garantía de retención cero por parte del proveedor.

## Compatibilidad

Se conservan las rutas V3/V4 y se agregan tablas nuevas. No se eliminan tablas, columnas ni datos anteriores. Se mantiene `.env`, SQLite y los repositorios Git originales cuando se sigue el procedimiento de actualización.

El tipo interno de evento y plantilla `followup_12h` se conserva por compatibilidad aunque el umbral sea configurable. Si cambiás el umbral, revisá también el asunto y texto de la plantilla en Comunicaciones: no se modifica tu redacción automáticamente. El indicador histórico del panel conserva su clave API original.
