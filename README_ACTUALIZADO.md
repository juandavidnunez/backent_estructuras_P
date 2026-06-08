# 🛫 SkyRoute Planner - Backend

Sistema de planificación de rutas aéreas para América Latina con gestión de presupuestos, trabajos regionales y desvíos de emergencia.

## 🚀 Inicio Rápido

### Requisitos
- Python 3.10+
- pip o uv (gestor de paquetes Python)

### Instalación

```bash
# Instalar dependencias
pip install -r requirements.txt

# O con uv (recomendado)
uv pip install -r requirements.txt
```

### Ejecutar el Servidor

```bash
# Desarrollo con hot-reload
python -m uvicorn main:app --reload

# Producción
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

El servidor estará disponible en `http://127.0.0.1:8000`

### Verificar Instalación

```bash
# Ejecutar suite de pruebas
python test_system.py

# Verificar endpoint de health
curl http://127.0.0.1:8000/health
# Respuesta esperada: {"status":"ok","nodes":31}
```

## 📚 Documentación API

Una vez iniciado el servidor, la documentación interactiva está disponible en:
- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

## 🌍 Red de Aeropuertos

El sistema incluye **31 aeropuertos** en América Latina:

### Hubs Principales
- 🇨🇴 Bogotá (BOG)
- 🇨🇴 Medellín (MDE)
- 🇵🇪 Lima (LIM)
- 🇨🇱 Santiago (SCL)
- 🇦🇷 Buenos Aires (EZE)
- 🇧🇷 São Paulo (GRU)
- 🇧🇷 Río de Janeiro (GIG)
- 🇵🇦 Ciudad de Panamá (PTY)
- 🇲🇽 Ciudad de México (MEX)
- Y más...

## ✨ Características Principales

### 🎯 R1 - Carga de Red
- Grafo dirigido ponderado con 31 aeropuertos
- Múltiples tipos de aeronaves (Comercial, Regional, Hélice)
- Rutas con costos diferenciados por aeronave

### 🗺️ R2 - Planificación de Rutas
- Algoritmo de Dijkstra para rutas óptimas
- Optimización por costo, tiempo o distancia
- BFS/DFS para cobertura máxima
- Filtrado de aeropuertos secundarios

### 💼 R3 - Viajes Dinámicos
- Sistema de presupuesto con restricciones
- **Trabajos regionales diferenciados** (31 aeropuertos únicos)
- Costos obligatorios:
  - Alimentación cada 8 horas
  - Alojamiento cada 20 horas
- Actividades opcionales por aeropuerto
- Rutas subsidiadas (máx 20% de distancia total)

### 🚨 R4 - Interrupciones y Desvíos
- Bloqueo/desbloqueo dinámico de rutas
- **Desvío de emergencia durante vuelos** ✨ NUEVO
- Recalculación automática de rutas
- Detección de vuelos en tránsito

### 📊 R5 - Reportes
- Informes detallados de viajes
- Estadísticas de costos y tiempos
- Historial de actividades y trabajos

## 🔧 Mejoras Recientes

### ✅ Trabajos Diferenciados por Región
Cada aeropuerto ahora tiene trabajos únicos que reflejan su cultura local:
- 🇵🇪 **Cusco:** Guía de expedición a Machu Picchu ($12/h)
- 🇦🇷 **Buenos Aires:** Instructor de tango ($11/h)
- 🇲🇽 **Guadalajara:** Bartender de tequila, Mariachi profesional
- 🇧🇷 **Río de Janeiro:** Instructor de samba ($10/h)
- 🇧🇷 **Brasília:** Arquitecto especialista en Niemeyer ($13.5/h)

### ✅ Sistema de Recaudo Verificado
- Logs de depuración para auditoría
- Validación automática de costos obligatorios
- Tracking preciso de horas acumuladas

### ✅ Desvío de Emergencia
- Detección automática de bloqueos durante vuelos
- Búsqueda inteligente de aeropuertos alternativos
- Priorización: origen → alternativa cercana → emergencia

### ✅ Navegación Mejorada
- Filtrado robusto de rutas bloqueadas
- Validaciones explícitas y mensajes claros
- Logs de depuración para diagnóstico

## 📁 Estructura del Proyecto

```
backent_estructuras_P/
├── api/                    # Definiciones de rutas (deprecated)
├── app/                    # Lógica principal
│   ├── algorithms.py       # Implementaciones de Dijkstra, BFS, DFS
│   ├── graph.py           # Estructura del grafo
│   ├── loader.py          # Carga de network.json
│   ├── models.py          # Esquemas Pydantic
│   └── services.py        # Capa de servicios (business logic)
├── core/                   # Algoritmos base
│   ├── bfs_dfs.py         # BFS y DFS
│   ├── dijkstra.py        # Dijkstra optimizado
│   ├── graph.py           # Interfaz de grafo
│   └── models.py          # Modelos de datos
├── data/                   # Datos
│   └── network.json       # Red de aeropuertos
├── features/              # Requerimientos R2-R5
│   ├── dynamic.py         # R3: Viajes dinámicos
│   ├── interruptions.py   # R4: Bloqueos y desvíos
│   ├── planner.py         # R2: Planificación
│   └── reporter.py        # R5: Reportes
├── tests/                 # Pruebas unitarias
├── config.py              # Configuración global
├── main.py                # Punto de entrada FastAPI
├── test_system.py         # Suite de pruebas integradas
└── requirements.txt       # Dependencias
```

## 🧪 Pruebas

### Suite de Pruebas Automatizadas

```bash
python test_system.py
```

**Pruebas incluidas:**
1. ✅ Trabajos diferenciados por región (31/31 únicos)
2. ✅ Sistema de recaudo funcional
3. ✅ Desvío de emergencia operativo
4. ✅ Navegación sin errores

### Pruebas Manuales

```bash
# Cargar el grafo
curl http://127.0.0.1:8000/api/v1/graph/load

# Iniciar un viaje
curl -X POST http://127.0.0.1:8000/api/v1/dynamic/start \
  -H "Content-Type: application/json" \
  -d '{"origin": "BOG", "initial_budget": 1000, "time_hours": 100}'

# Ver vuelos disponibles
curl "http://127.0.0.1:8000/api/v1/dynamic/flights?session_id=<SESSION_ID>"
```

## 🛠️ Desarrollo

### Agregar Nuevos Aeropuertos

Editar `data/network.json`:

```json
{
  "id": "NEW",
  "nombre": "Nuevo Aeropuerto",
  "ciudad": "Ciudad",
  "pais": "País",
  "zonaHoraria": "America/Timezone",
  "esHub": true,
  "costoAlojamiento": 50.0,
  "costoAlimentacion": 12.0,
  "aerolineas": ["Aerolínea 1"],
  "actividades": [
    {"nombre": "Actividad", "tipo": "opcional", "duracionMin": 120, "costoUSD": 10.0}
  ],
  "trabajos": [
    {"nombre": "Trabajo Regional", "tarifaHora": 8.0, "maxHoras": 6}
  ]
}
```

### Logs de Depuración

El sistema incluye logs informativos en operaciones críticas:
- ✓ Vuelos exitosos
- ✓ Sistema de recaudo activo
- ✓ Vuelos disponibles por aeropuerto
- ✓ Desvíos de emergencia

Para desactivar en producción, ajusta el nivel de logging en `main.py`.

## 📊 Métricas del Sistema

| Métrica | Valor |
|---------|-------|
| Aeropuertos | 31 |
| Rutas directas | ~70 |
| Tipos de aeronave | 3 |
| Trabajos únicos | 31 conjuntos |
| Cobertura geográfica | América Latina |

## 🔒 Seguridad

- Validaciones estrictas de entrada
- Manejo robusto de errores
- CORS configurado para frontend
- Sin ejecución de código dinámico

## 📞 Soporte y Documentación

- **Documentación técnica:** `MEJORAS_REALIZADAS.md`
- **Resumen ejecutivo:** `RESUMEN_FINAL.md`
- **API interactiva:** http://127.0.0.1:8000/docs

## 📄 Licencia

Este proyecto es parte de un trabajo académico.

---

**Desarrollado para el curso de Estructuras de Datos** 🎓
