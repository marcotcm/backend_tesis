# RCM Confiabilidad Industrial API

Backend REST para gestionar activos industriales, planes de mantenimiento y datos
de confiabilidad. Está construido con FastAPI, SQLAlchemy asíncrono, PostgreSQL y
Supabase Auth.

## Funcionalidades

- **Taxonomía de equipos:** jerarquía de planta, sistema, subsistema y componente;
  permite crear, consultar y actualizar categorías. Una categoría solo puede
  eliminarse si no tiene equipos ni subcategorías asociados.
- **Equipos:** creación, consulta, listado paginado y actualización de activos.
  Valida la taxonomía y evita tags duplicados. La baja es lógica: marca el equipo
  como inactivo para conservar su registro.
- **Mantenimientos:** administra planes preventivos, predictivos, correctivos y
  adaptativos (IA), con filtro por equipo y baja lógica.
- **Historial de métricas:** registra lecturas de temperatura, vibración, horas de
  operación y variables adicionales en JSON. Cada lectura conserva el usuario y
  la fecha de registro; se puede consultar el historial paginado por equipo.
- **Criticidad:** registra una evaluación por equipo con puntuaciones de seguridad,
  ambiente, operación, costo de mantenimiento, RPN y nivel de criticidad.
- **Recomendaciones de IA:** permite registrar, consultar, editar y aceptar o
  rechazar recomendaciones, con trazabilidad de quién las resolvió. La generación
  automática mediante IA aún no está integrada.
- **Correcciones humanas:** permite guardar la corrección de un experto para una
  recomendación ya aceptada o rechazada; se admite una corrección por recomendación.
- **Usuarios y autenticación:** utiliza Supabase Auth para registro, inicio de
  sesión, renovación de tokens y recuperación de contraseña. Los perfiles y roles
  se almacenan en PostgreSQL. La baja de usuario es lógica y también deshabilita
  la cuenta de autenticación.
- **Monitoreo:** endpoints raíz y de salud para comprobar la aplicación y las
  conexiones a PostgreSQL y Supabase.

## Tecnologías

- Python 3.12
- FastAPI y Uvicorn
- SQLAlchemy 2 con sesiones asíncronas
- PostgreSQL mediante `asyncpg`
- Pydantic Settings para configuración
- Supabase Auth y SDK de Supabase
- PyJWT para leer los JWT de Supabase

## Requisitos previos

1. Python 3.12 instalado.
2. Una base de datos PostgreSQL accesible mediante una URL asíncrona compatible
   con `asyncpg`.
3. Un proyecto de Supabase con Auth configurado y las claves correspondientes.
4. Las tablas, tipos y restricciones de base de datos requeridos por los modelos.
   Este repositorio no incluye migraciones ni crea el esquema automáticamente al
   iniciar.

## Instalación y ejecución en Windows

Desde la carpeta `backend_tesis`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Crea un archivo `.env` en esa carpeta y configura las variables requeridas:

```dotenv
DATABASE_URL=postgresql+asyncpg://usuario:contraseña@host:5432/base_de_datos
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_ANON_KEY=tu-clave-anon
SUPABASE_SERVICE_ROLE_KEY=tu-clave-service-role
SUPABASE_JWT_SECRET=tu-secreto-jwt
```

No compartas ni subas el archivo `.env` al repositorio. La clave `SERVICE_ROLE`
debe permanecer exclusivamente en el servidor.

Inicia el servidor de desarrollo:

```powershell
uvicorn main:app --reload
```

Ejecuta el comando desde `backend_tesis`, donde se encuentra `main.py`. La API
quedará disponible en `http://127.0.0.1:8000`.

## Documentación y monitoreo

| URL | Descripción |
| --- | --- |
| `/docs` | Documentación interactiva Swagger/OpenAPI |
| `/redoc` | Documentación ReDoc |
| `/` | Estado básico de la aplicación |
| `/health` | Comprueba PostgreSQL y Supabase; responde con error HTTP 503 si alguno no está disponible |

Todas las rutas de negocio se agrupan bajo el prefijo `/api/v1`.

## Endpoints

Salvo donde se indique, `:id` representa un UUID. Los listados paginados aceptan
`skip` y `limit` (predeterminado: 0 y 100; límite máximo: 500).

### Usuarios — `/api/v1/usuarios`

| Método | Ruta | Acceso |
| --- | --- | --- |
| `POST` | `/registro` | Público |
| `POST` | `/login` | Público |
| `POST` | `/refresh` | Público; recibe `refresh_token` en el cuerpo |
| `POST` | `/recuperar-contrasena` | Público |
| `GET` | `/me` | Autenticado |
| `GET` | `/` | Roles `admin` o `technical_auditor` |
| `GET` | `/buscar?nombre=...` | Autenticado |
| `GET` | `/buscar-email?email=...` | Autenticado |
| `GET` | `/{id}` | Autenticado |
| `PATCH` | `/{id}` | Propietario del perfil o `admin` |
| `DELETE` | `/{id}` | Propietario del perfil o `admin`; baja lógica |

El perfil valida el formato de identificación venezolana (`V-`, `E-` o `P-`),
teléfonos nacionales y mayoría de edad cuando se informa la fecha de nacimiento.
Los roles disponibles son `admin`, `rcm_engineer` y `technical_auditor`; los turnos
son `daytime` y `nighttime`.

### Taxonomía — `/api/v1/taxonomia`

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Crear categoría |
| `GET` | `/` | Listar categorías |
| `GET` | `/{id}` | Consultar categoría |
| `PATCH` | `/{id}` | Actualizar categoría |
| `DELETE` | `/{id}` | Eliminar si no tiene equipos ni subcategorías |

### Equipos — `/api/v1/equipos`

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Crear equipo |
| `GET` | `/` | Listar equipos; admite `taxonomy_id` |
| `GET` | `/{id}` | Consultar equipo |
| `PATCH` | `/{id}` | Actualizar equipo |
| `DELETE` | `/{id}` | Dar de baja lógicamente el equipo |
| `POST` | `/bulk?taxonomy_name={nombre}` | Importar lote CSV/XLSX para un nombre de taxonomía único |
| `POST` | `/bulk?taxonomy_id={uuid}` | Importar lote CSV/XLSX por UUID, también para resolver nombres duplicados |
| `GET` | `/export?taxonomy_name={nombre}&format=xlsx` | Exportar por nombre único de taxonomía |
| `GET` | `/export?taxonomy_id={uuid}&format=xlsx` | Exportar por UUID, también para resolver nombres duplicados |

Los tipos admitidos son `Estatico`, `Rotativo`, `Electrico` e
`Instrumentacion`. Los estados operativos son `operational`, `standby`,
`under_maintenance` y `failed`.

La hoja `Equipos` de importaciones y exportaciones usa estos encabezados, en este orden:
`taxonomy_id`, `tag_number`, `name`, `equipment_type`, `operational_status`,
`brand`, `model`, `function_description`, `technical_specifications`. Para importar,
el cliente envía `taxonomy_name` o `taxonomy_id` como parámetro de consulta.
Si se envía `taxonomy_id`, el backend selecciona exactamente esa taxonomía; también
se puede enviar el nombre junto al UUID, en cuyo caso ambos deben coincidir.
Sin UUID, el backend busca un único nombre activo (ignorando mayúsculas y espacios
al inicio/final). `taxonomy_id` de cada fila puede quedar vacío o, si se proporciona,
debe coincidir con la taxonomía seleccionada.

En archivos XLSX se incluye además la hoja `Especificaciones`, con columnas
`tag_number`, `especificacion` y `valor`, una fila por característica técnica.
En ese formato, `technical_specifications` debe quedar vacío; el backend arma
el objeto JSON asociando las filas por tag. También se siguen aceptando XLSX
antiguos de una sola hoja y CSV con el objeto JSON en `technical_specifications`.
La carga es todo-o-nada: si hay errores, no se inserta
ninguna fila y la respuesta identifica las filas problemáticas. El creador se
toma del usuario autenticado; los tags duplicados se rechazan incluso si el
equipo existente fue dado de baja. La exportación incluye también equipos dados
de baja. La exportación también acepta `taxonomy_name` o `taxonomy_id` con la misma
resolución que la importación. El formato predeterminado es XLSX;
`format=csv` produce CSV UTF-8 con BOM.

Si el nombre no existe o el UUID no corresponde a una taxonomía activa, la
importación/exportación responde `404`; si el nombre es ambiguo y no se envía
UUID, responde `409` indicando que se debe seleccionar una taxonomía por UUID.

### Mantenimientos — `/api/v1/mantenimientos`

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Crear plan |
| `GET` | `/` | Listar planes; admite `equipment_id` |
| `GET` | `/{id}` | Consultar plan |
| `PATCH` | `/{id}` | Actualizar plan |
| `DELETE` | `/{id}` | Dar de baja lógicamente el plan |

Los tipos son `Preventivo`, `Predictivo`, `Correctivo` y `Adaptativo (IA)`.

### Métricas — `/api/v1/metricas`

Estas rutas requieren un token JWT válido.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Registrar lectura; el usuario se obtiene del token |
| `GET` | `/equipo/{equipment_id}` | Consultar historial paginado del equipo |

Se validan temperaturas entre -50 y 1000 °C, vibraciones no negativas y horas de
operación no negativas. `specific_metrics` permite enviar otras variables como
presión o voltaje.

### Criticidad — `/api/v1/criticidad`

Estas rutas requieren un token JWT válido.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Crear evaluación |
| `GET` | `/` | Listar; admite filtro `equipment_id` |
| `GET` | `/{id}` | Consultar evaluación |
| `PATCH` | `/{id}` | Actualizar evaluación |

Las puntuaciones aceptan valores entre 0 y 100. El nivel es `Alta`, `Media` o
`Baja`, y cada equipo admite una evaluación registrada.

### Recomendaciones — `/api/v1/recomendaciones`

Estas rutas requieren un token JWT válido.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Registrar recomendación |
| `GET` | `/` | Listar recomendaciones |
| `GET` | `/{id}` | Consultar recomendación |
| `PATCH` | `/{id}` | Actualizar contenido |
| `PATCH` | `/{id}/status` | Cambiar a `Pendiente`, `Aceptada` o `Rechazada` |

Al aceptar o rechazar una recomendación se registran el usuario responsable y
la fecha de resolución. La confianza debe estar entre 0 y 100.

### Correcciones humanas — `/api/v1/correcciones`

Estas rutas requieren un token JWT válido.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `POST` | `/` | Registrar corrección de una recomendación resuelta |
| `GET` | `/` | Listar correcciones |
| `GET` | `/{id}` | Consultar corrección |
| `PATCH` | `/{id}` | Actualizar texto de corrección |

### Dashboard — `/api/v1/dashboard`

Estas rutas requieren un token JWT válido.

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/resumen` | Devuelve estadísticas agregadas y actividad reciente; `activity_limit` permite de 1 a 50 eventos (predeterminado: 10). |

El resumen incluye equipos totales y por estado operativo, equipos activos con
criticidad `Alta`, órdenes de trabajo pendientes/en proceso, órdenes terminadas
durante el mes UTC actual, órdenes vencidas, fallas registradas, promedio del
downtime informado en fallas y actividad reciente de órdenes, fallas,
mantenimientos y recomendaciones. `total` cuenta todos los registros de equipos;
`inactive` cuenta los inactivos o dados de baja lógicamente. El contador
`critical` solo incluye equipos activos/no eliminados con `criticality_level =
'Alta'`.

No se devuelve un índice de disponibilidad ni MTBF/MTTR: el esquema actual no
define la ventana ni los denominadores necesarios para esos indicadores. Tampoco
se incluyen alarmas activas ni el bloque de salud operativa de planta, que queda
reservado para la futura integración de IA. El endpoint es de solo lectura y no
requiere cambios en la base de datos.

## Estructura del proyecto

```text
backend_tesis/
├── api/v1/
│   ├── api.py                 # Registro central de routers
│   └── endpoints/             # Controladores HTTP
├── core/                      # Configuración y seguridad
├── crud/                      # Consultas y persistencia
├── db/                        # Sesiones PostgreSQL y cliente Supabase
├── models/                    # Modelos SQLAlchemy
├── schemas/                   # Validación y serialización Pydantic
├── services/                  # Reglas de negocio
├── main.py                    # Aplicación FastAPI
└── requirements.txt
```

## Notas de implementación

- Las bajas de equipos y mantenimientos conservan el registro y lo marcan
  `is_active = false`; los listados y consultas operativas excluyen registros
  inactivos.
- La baja de usuarios marca `deleted_at`, desactiva `is_active` y revoca el acceso
  correspondiente en Supabase Auth. Las búsquedas de usuarios excluyen las bajas.
- La taxonomía se elimina físicamente solo después de comprobar que no tenga
  dependencias.
- Los routers de equipos, taxonomía y mantenimientos no exigen autenticación en
  sus controladores actuales. Las operaciones de métricas, criticidad,
  recomendaciones y correcciones sí requieren un usuario autenticado.
- El middleware CORS está configurado actualmente para todos los orígenes. Antes
  de desplegar en producción, debe limitarse a los dominios autorizados.
- SQLAlchemy usa conexiones asíncronas y `NullPool`, pensado para despliegues
  donde el pool de conexiones lo administra PostgreSQL/Supabase.
