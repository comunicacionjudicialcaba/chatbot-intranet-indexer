Este repositorio contiene el servicio de indexación para un chatbot interno que permite consultar información publicada en la intranet a partir de documentos almacenados en Google Drive.

El objetivo es leer automáticamente notas y planillas que se actualizan a diario, estructurar esa información y dejarla lista para ser consultada luego a través de un chatbox web.

🧠 ¿Qué hace este proyecto?

Accede de forma segura y de solo lectura a una carpeta específica de Google Drive.

Lee documentos Google Docs y Google Sheets que contienen:

textos completos de notas

metadatos (fecha, título, autor, sección, URL)

Prepara esa información para:

búsquedas semánticas

respuestas en lenguaje natural

entrega de links a la nota real publicada en la intranet

Este repositorio no contiene el frontend del chatbot, solo la lógica de acceso e indexación de contenidos.

🔐 Seguridad

El acceso a Google Drive se realiza mediante una Service Account.

Las credenciales no están en el código ni en el repositorio.

Se inyectan como variable de entorno:

GOOGLE_SERVICE_ACCOUNT_JSON


El acceso está limitado a una carpeta concreta del Drive.

Permisos: solo lectura.

☁️ Infraestructura

Desplegado en Render

Pensado para ejecutarse como:

Web Service (fase inicial / pruebas)

Cron Job (ejecución periódica automática)

No depende de ninguna computadora local.

📁 Estructura esperada de los datos

Google Docs:

Fecha

Título

Bajada

Texto completo

Google Sheets:

Fecha

Título

Autor

Sección

URL a la nota publicada

La relación entre documentos se realiza por título + fecha (o URL cuando esté disponible).

🚧 Estado del proyecto

🟡 En desarrollo
Actualmente:

Acceso a Drive verificado

Infraestructura configurada

Próximo paso: indexación completa y conexión con el chatbot

ℹ️ Notas

Este proyecto es de uso interno y no oficial, con fines informativos y experimentales.
No reemplaza a los canales institucionales de comunicación.
