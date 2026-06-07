# Asesor de Automóviles — Documentación para IA

> **Objetivo**: generar una base de datos del mercado automotor chileno que permita rankear vehículos por relación costo/calidad, incluyendo precios de venta, fallas comunes y disponibilidad de repuestos.

---

## 1. Estructura del proyecto

```
asesor_automoviles/
├── docs/
│   └── PROYECTO.md              ← este archivo
├── data/
│   ├── autos_chile.db           # SQLite (motor de scraping, ~1,250 registros)
│   └── listings.parquet         # Parquet exportado automáticamente al finalizar
├── src/
│   ├── config.py                # Configuración central (pydantic-settings)
│   ├── database/
│   │   ├── connection.py        # Engine SQLAlchemy + init_db()
│   │   └── models.py            # Tablas: Brand, Model, Listing, ListingSnapshot
│   ├── scrapers/
│   │   ├── base.py              # Clase base con Playwright (para scrapers futuros)
│   │   └── chileautos.py        # Scraper principal de chileautos.cl
│   └── normalizers/
│       └── car_normalizer.py    # Normalizador fuzzy de marcas/modelos (no usado actualmente)
├── run_scraper.py               # Entry point CLI
├── stats.py                     # Estadísticas rápidas de la BD
├── export_parquet.py            # Export manual a Parquet (redundante, el scraper lo hace solo)
├── requirements.txt
└── README.md
```

---

## 2. Qué se hizo hasta ahora

### 2.1 Scraper de chileautos.cl

**Descubrimiento clave**: se intentó usar Playwright (navegador real) pero no se pudo instalar Chromium en Ubuntu 26.04. Inspeccionando el HTML de la página se descubrió que chileautos.cl funciona con Next.js y expone una API REST interna que devuelve todos los datos en JSON, sin necesidad de navegador.

**Endpoint**: `GET https://www.chileautos.cl/_api/search-core/?offset=N`

La respuesta es un JSON de ~1 MB que contiene un árbol de componentes React con los datos de los listings embebidos como metadatos de tracking. Cada listing tiene un `networkId` (ej: `CL-AD-20187833`, `CP-AD-8517056`, `GI-AD-889004`) y los campos `make`, `model`, `year`, `price`, `state` (región), `type` (Nuevo/Usado) dispersos en el JSON.

**Parser**: usa regex para extraer los campos alrededor de cada `networkId`. No usa BeautifulSoup ni DOM parsing porque los datos están en JSON, no en HTML.

```python
# Flujo:
# 1. GET /_api/search-core/?offset=N
# 2. Regex extrae networkId + campos circundantes (make, model, year, price, state, type...)
# 3. Deduplica por source_id en SQLite
# 4. Normaliza marca/modelo
# 5. Guarda en BD
# 6. Al finalizar, exporta todo a Parquet
```

**Paginación**:
- `PAGE_SIZE = 24` (aunque la API devuelve ~27 listings por página)
- ~18 listings por página son "destacados" (premium/featured) que se repiten en todas las páginas
- ~3-6 son orgánicos únicos que rotan
- Total disponible según API: ~63,879
- Listings únicos extraídos: 1,250 (se agotaron en página 290)
- Para extraer el resto se necesitaría scrapear con múltiples ordenamientos (por precio, año, etc.)

### 2.2 Base de datos (SQLite)

**¿Por qué SQLite y no guardar directo a Parquet?**
- Deduplicación eficiente: `SELECT WHERE source_id = ?` es O(1) con índice, vs escanear todo un Parquet
- Historial de precios: tabla `listing_snapshots` guarda cada cambio de precio
- Relaciones: marcas ↔ modelos ↔ listings con foreign keys y JOINs
- Scraping incremental: cada ejecución solo agrega listings nuevos, no re-procesa los existentes

**Tablas**:

| Tabla | Columnas clave | Propósito |
|-------|---------------|-----------|
| `brands` | id, name, slug | Marcas normalizadas (único por slug) |
| `models` | id, brand_id, name, slug | Modelos (único por brand_id + slug) |
| `listings` | id, source, source_id, brand_id, model_id, year, price, location, is_sold, url, first_seen, last_seen | Listings individuales |
| `listing_snapshots` | id, listing_id, price, is_sold, scraped_at | Historial de cambios de precio |

### 2.3 Normalización de marcas

Se implementaron tres mecanismos en `chileautos.py`:

1. **`BRAND_NORMALIZE`**: diccionario que mapea variantes de nombres a forma canónica (ej: `"SKODA"` → `"Skoda"`, `"Mercedes Benz"` → `"Mercedes-Benz"`, `"VW"` → `"Volkswagen"`, `"Peugeot"` → `"Peugeot"`).

2. **`NON_BRAND_WORDS`**: set de palabras que no son marcas y deben ignorarse (`"motorhome"`, `"otra marca"`, `"bayliner"`, `"hechizo"`, etc.).

3. **`BRAND_FIXES`**: correcciones de datos erróneos del API (`"Compass"` → marca `"Jeep"`, modelo `"Compass"`).

La normalización se ejecuta en `_find_or_create_brand_model()`. Las marcas/modelos nuevos se insertan en SQLite automáticamente; los existentes se recuperan de un cache en memoria (`_brand_cache`, `_model_cache`) para evitar queries repetidos.

### 2.4 Exportación a Parquet

Al finalizar cada scrape, `_export_parquet()` hace un JOIN de las 3 tablas y escribe `data/listings.parquet` con estas columnas:

| Columna | Tipo |
|---------|------|
| marca | str |
| modelo | str |
| año | int |
| precio_clp | float |
| moneda | str |
| kilometraje | int (nullable) |
| region | str |
| vendido | bool |
| url | str |
| fuente | str |
| source_id | str |
| primera_vez_visto | datetime |
| ultima_vez_visto | datetime |

### 2.5 Scripts auxiliares

- **`run_scraper.py`**: CLI con argparse. Flags: `--pages N`, `--all` (hasta agotar), `--start-offset N` (reanudar), `--reset` (borrar BD).
- **`stats.py`**: imprime estadísticas (marcas, precios, años, regiones, top listings).
- **`export_parquet.py`**: export manual a Parquet por si se necesita sin correr el scraper.

### 2.6 Datos actuales (1,250 listings)

| Métrica | Valor |
|---------|-------|
| Listings | 1,250 |
| Marcas únicas | 102 |
| Modelos únicos | 515 |
| Años | 1967 – 2026 |
| Precio promedio | $19,017,991 CLP |
| Precio mín / máx | $1,600,000 / $170,000,000 |
| Regiones | 16 (todas las de Chile) |
| Top marca | Chevrolet (140 listings) |

---

## 3. Desafíos enfrentados y soluciones

### 3.1 Playwright no soportado en Ubuntu 26.04

**Problema**: `playwright install chromium` falló con `ERROR: Playwright does not support chromium on ubuntu26.04-x64`. Tampoco Firefox ni WebKit. No había `sudo` para instalar chromium del sistema ni snap.

**Solución**: Se inspeccionó el HTML de chileautos.cl con `httpx` y se descubrió que los datos vienen en un blob JSON de 1 MB dentro de la respuesta del endpoint `/_api/search-core/`. Se reescribió el scraper para usar solo `httpx` + regex en vez de Playwright. Esto además lo hizo 10x más rápido y ligero.

### 3.2 Paginación ineficiente por listings destacados

**Problema**: la API devuelve ~27 listings por página pero ~18 son "destacados" que se repiten idénticos en todas las páginas. Solo ~3-6 son orgánicos únicos. Para obtener 63k listings se necesitarían ~7,000 páginas (~3 horas con delay de 0.5s).

**Solución parcial**: se agregó `--start-offset` para reanudar scrapes interrumpidos. La deduplicación en SQLite evita guardar repetidos aunque se re-procesen páginas. Para extraer el 100% de listings haría falta scrapear con múltiples ordenamientos (precio ascendente, precio descendente, año, etc.) y combinar resultados.

### 3.3 Normalización de marcas inconsistentes

**Problema**: el API devuelve nombres con capitalización inconsistente (`SKODA` vs `Skoda`), errores de tipeo (`Peugeot` en vez de `Peugeot`), y a veces confunde marca con modelo (`Compass` como marca en vez de `Jeep Compass`).

**Solución**: tres capas de normalización (`BRAND_NORMALIZE`, `NON_BRAND_WORDS`, `BRAND_FIXES`) aplicadas en cascada antes de insertar en BD. Se usa `unicodedata.normalize('NFKD')` para eliminar acentos y `slug` como clave canónica.

---

## 4. Cómo proseguir

### 4.1 Prioridad alta: extraer más listings

Actualmente solo se extrajeron 1,250 de ~63,879 disponibles. Estrategia:

1. Scrapear con **múltiples ordenamientos** (la API acepta query params):
   - `?offset=N&sort=price_asc` → listings baratos primero
   - `?offset=N&sort=price_desc` → listings caros primero
   - `?offset=N&sort=year_desc` → más nuevos primero
   - `?offset=N&sort=year_asc` → más viejos primero
   
2. Combinar y deduplicar por `source_id`. Con 4 ordenamientos se capturaría ~80% del catálogo.

3. Agregar más fuentes:
   - **yapo.cl**: marketplace grande, requiere análisis de su estructura
   - **mercadolibre.cl**: API semi-pública, scrapear por categoría "Autos"
   - **Facebook Marketplace**: difícil (requiere sesión, GraphQL interno)

### 4.2 Prioridad alta: fallas y problemas por modelo

Estrategia propuesta (no implementada):

1. Para cada modelo en la BD, buscar en Google/Bing: `"problemas comunes [marca] [modelo]"` y `"[marca] [modelo] fallas frecuentes"`
2. Extraer texto de foros (chw.net, foros.cl), reviews de YouTube, comentarios enGoogle Maps de talleres
3. Usar un LLM (GPT-4o, Claude) para extraer datos estructurados:
   ```json
   {
     "modelo": "Toyota Hilux",
     "fallas": [
       {"componente": "motor", "problema": "pérdida de potencia en altura", "frecuencia": "alta"},
       {"componente": "transmisión", "problema": "ruido en 3ra marcha", "frecuencia": "media"}
     ]
   }
   ```
4. Guardar en tabla nueva `failures` relacionada a `models`

### 4.3 Prioridad media: repuestos y disponibilidad

Estrategia propuesta (no implementada):

1. Scrapear **MercadoLibre Chile** buscando `"repuesto [marca] [modelo]"` por categorías de repuestos
2. Extraer: nombre del repuesto, precio, condición (nuevo/usado/genérico), cantidad de publicaciones como proxy de disponibilidad
3. Scrapear sitios especializados: **repuestoscarros.cl**, **deremate.cl**
4. Agregar tabla `parts` relacionada a `models`

### 4.4 Prioridad media: dashboard

Crear una app Streamlit (`streamlit run dashboard.py`) con:
- Filtros por marca, modelo, año, precio, región
- Gráficos de distribución de precios
- Tabla de ranking costo/calidad (precio vs fallas vs disponibilidad de repuestos)

### 4.5 Mejoras técnicas

- Mover configuración de delay y headers a `.env`
- Agregar reintentos con backoff exponencial para requests fallidos
- Agregar rotación de User-Agents
- Implementar el patrón Strategy para scrapers multi-fuente
- Tests unitarios para el parser y normalizador

---

## 5. Comandos rápidos

```bash
# Scraping
python3 run_scraper.py --pages 100              # 100 páginas
python3 run_scraper.py --all                    # hasta agotar (~290 págs, 1,250 listings)
python3 run_scraper.py --all --reset            # empezar de cero
python3 run_scraper.py --all --start-offset 7000 # reanudar desde offset

# Estadísticas
python3 stats.py

# Export manual a Parquet (redundante, el scraper ya lo hace)
python3 export_parquet.py

# Dependencias
pip3 install --break-system-packages -r requirements.txt
```

---

## 6. Dependencias

```
playwright>=1.45.0        # solo para scrapers futuros con navegador, no usado actualmente
sqlalchemy>=2.0.30        # ORM para SQLite
rapidfuzz>=3.9.0          # fuzzy matching de marcas (normalizers/)
pydantic>=2.7.0           # modelos de datos
pydantic-settings>=2.3.0  # configuración con .env
httpx>=0.27.0             # HTTP client para el scraper
tqdm>=4.66.0              # barras de progreso
pandas                     # exportación Parquet
pyarrow                    # motor Parquet para pandas
openpyxl                   # (ya no se usa, se eliminó export a Excel)
```
