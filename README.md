# 🖼️ Conversor de Imágenes

App local en [Streamlit](https://streamlit.io) para **convertir formato, comprimir y redimensionar imágenes**, una a una o en lote. Todo el procesamiento ocurre en tu máquina: ningún archivo sale a internet.

![CI](https://github.com/KarCan2023/images-expert/actions/workflows/ci.yml/badge.svg)

---

## Qué hace

- **Convierte** entre JPG, PNG, WEBP, BMP y TIFF (o mantiene el formato original).
- **Comprime** con control de calidad (10–100) y opción de WEBP sin pérdida.
- **Redimensiona** por porcentaje, por ancho máximo (manteniendo proporción) o a dimensiones exactas.
- **Procesa en lote** y descarga todo en un ZIP.
- **Corrige la orientación EXIF**: las fotos de móvil no salen tumbadas.
- **Conserva o descarta metadatos** (EXIF y perfil de color ICC) — útil para quitar geolocalización antes de publicar.
- Muestra **peso antes/después, dimensiones y % de ahorro** por imagen y del lote completo.

## Instalación

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/KarCan2023/images-expert.git
cd images-expert

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Uso

```bash
streamlit run app.py
```

Se abre en `http://localhost:8501`. Sube las imágenes, ajusta las opciones en el panel lateral y pulsa **Procesar imágenes**.

### Con Docker

```bash
docker build -t conversor-imagenes .
docker run --rm -p 8501:8501 conversor-imagenes
```

### En GitHub Codespaces / Dev Container

El repo incluye `.devcontainer/devcontainer.json`: al abrir el Codespace se instalan las dependencias y la app arranca sola en el puerto 8501.

## Uso como librería

La lógica vive en `image_tools.py` y no depende de Streamlit, así que puedes usarla desde cualquier script:

```python
from pathlib import Path
from image_tools import OpcionesProceso, procesar_imagen

opciones = OpcionesProceso(
    formato="WEBP",
    calidad=80,
    modo_resize="Ancho máximo (mantiene proporción)",
    ancho=1200,
    conservar_metadatos=False,
)

origen = Path("foto.jpg")
resultado = procesar_imagen(origen.read_bytes(), origen.name, opciones)

Path(resultado.nombre).write_bytes(resultado.datos)
print(f"{resultado.peso_original} → {resultado.peso_final} bytes ({resultado.ahorro:.1f}% de ahorro)")
```

Para varios archivos, `procesar_lote()` acepta un iterable de `(nombre, bytes)`, no se detiene ante un archivo corrupto (lo acumula en `.errores`) y `crear_zip()` empaqueta el resultado.

## Estructura

```
.
├── app.py                  # Interfaz Streamlit (solo UI y estado)
├── image_tools.py          # Lógica de procesamiento (sin Streamlit, testeable)
├── tests/                  # Suite de pytest
├── requirements.txt        # Dependencias de ejecución
├── requirements-dev.txt    # + pytest y ruff
├── .streamlit/config.toml  # Límite de subida, tema
├── Dockerfile
└── .github/workflows/ci.yml
```

## Desarrollo

```bash
pip install -r requirements-dev.txt

pytest                  # tests
ruff check .            # lint
ruff format .           # formato
```

La CI corre lint, formato, tests en Python 3.10/3.11/3.12 y un smoke test que verifica que la app levanta.

## Notas técnicas

- **Límite de tamaño**: 50 MB por archivo (ajustable en `.streamlit/config.toml`) y 100 megapíxeles por imagen (`LIMITE_PIXELES` en `image_tools.py`), como protección ante *decompression bombs*.
- **Transparencia**: al convertir a un formato sin canal alfa (JPG, BMP) el fondo se aplana a blanco en lugar de ennegrecerse.
- **JPEG progresivo** y **PNG con `compress_level=9`** por defecto: mismo resultado visual, menos bytes.
- **Nombres duplicados**: si dos archivos de origen se llaman igual, el ZIP los guarda como `foto.jpg` y `foto_2.jpg` en vez de pisarse.

## Licencia

MIT — ver [LICENSE](LICENSE).
