"""
Lógica de procesamiento de imágenes.

Este módulo NO depende de Streamlit: recibe bytes, devuelve bytes. Así puede
testearse con pytest y reutilizarse desde un script o una API.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

__all__ = [
    "FORMATOS",
    "FORMATOS_CON_CALIDAD",
    "MODOS_RESIZE",
    "OpcionesProceso",
    "ResultadoImagen",
    "ErrorImagen",
    "crear_zip",
    "formato_desde_nombre",
    "humano",
    "procesar_imagen",
    "procesar_lote",
]

# Etiqueta visible -> formato de Pillow (None = mantener el del archivo original)
FORMATOS: dict[str, str | None] = {
    "Mantener original": None,
    "JPG": "JPEG",
    "PNG": "PNG",
    "WEBP": "WEBP",
    "BMP": "BMP",
    "TIFF": "TIFF",
}

# Formatos donde el slider de calidad tiene efecto
FORMATOS_CON_CALIDAD = frozenset({"JPEG", "WEBP"})

# Extensiones de entrada aceptadas -> formato de Pillow
ALIAS_EXTENSION: dict[str, str] = {
    "JPG": "JPEG",
    "JPEG": "JPEG",
    "JPE": "JPEG",
    "JFIF": "JPEG",
    "PNG": "PNG",
    "WEBP": "WEBP",
    "BMP": "BMP",
    "DIB": "BMP",
    "TIF": "TIFF",
    "TIFF": "TIFF",
}

EXTENSION_SALIDA: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "BMP": "bmp",
    "TIFF": "tiff",
}

MIME: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}

# Modos de color que cada formato sabe escribir. Si el modo actual no está
# en la lista, se convierte antes de guardar (si no, Pillow lanza OSError).
MODOS_SOPORTADOS: dict[str, frozenset[str]] = {
    "JPEG": frozenset({"RGB", "L", "CMYK"}),
    "PNG": frozenset({"RGB", "RGBA", "L", "LA", "P", "I", "1"}),
    "WEBP": frozenset({"RGB", "RGBA"}),
    "BMP": frozenset({"RGB", "L", "P", "1"}),
    "TIFF": frozenset({"RGB", "RGBA", "L", "LA", "CMYK", "1"}),
}

SIN_CAMBIOS = "Sin cambios"
PORCENTAJE = "Porcentaje"
ANCHO_MAXIMO = "Ancho máximo (mantiene proporción)"
DIMENSIONES_EXACTAS = "Dimensiones exactas"
MODOS_RESIZE: tuple[str, ...] = (SIN_CAMBIOS, PORCENTAJE, ANCHO_MAXIMO, DIMENSIONES_EXACTAS)

# Tope de píxeles por imagen (~100 MP). Evita que un archivo manipulado agote
# la memoria del proceso (decompression bomb).
LIMITE_PIXELES = 100_000_000

LADO_MINIATURA = 480


class ErrorImagen(Exception):
    """Falla controlada al procesar una imagen concreta."""


@dataclass(frozen=True)
class OpcionesProceso:
    """Parámetros de conversión. Valores por defecto = no tocar nada."""

    formato: str | None = None
    calidad: int = 80
    modo_resize: str = SIN_CAMBIOS
    ancho: int = 0
    alto: int = 0
    porcentaje: int = 100
    conservar_metadatos: bool = True
    webp_sin_perdida: bool = False
    sufijo: str = "_procesado"

    def __post_init__(self) -> None:
        if self.formato is not None and self.formato not in EXTENSION_SALIDA:
            raise ValueError(f"Formato de salida no soportado: {self.formato}")
        if not 1 <= self.calidad <= 100:
            raise ValueError("La calidad debe estar entre 1 y 100")
        if self.modo_resize not in MODOS_RESIZE:
            raise ValueError(f"Modo de redimensionado no soportado: {self.modo_resize}")


@dataclass
class ResultadoImagen:
    nombre: str
    datos: bytes
    formato: str
    mime: str
    peso_original: int
    peso_final: int
    dimension_original: tuple[int, int]
    dimension_final: tuple[int, int]
    miniatura_original: bytes = b""
    miniatura_final: bytes = b""

    @property
    def ahorro(self) -> float:
        """Porcentaje de peso ahorrado. Negativo si el archivo creció."""
        if not self.peso_original:
            return 0.0
        return 100 * (1 - self.peso_final / self.peso_original)


@dataclass
class ResultadoLote:
    resultados: list[ResultadoImagen] = field(default_factory=list)
    errores: list[tuple[str, str]] = field(default_factory=list)

    @property
    def peso_original(self) -> int:
        return sum(r.peso_original for r in self.resultados)

    @property
    def peso_final(self) -> int:
        return sum(r.peso_final for r in self.resultados)

    @property
    def ahorro(self) -> float:
        if not self.peso_original:
            return 0.0
        return 100 * (1 - self.peso_final / self.peso_original)


def humano(num_bytes: float) -> str:
    """Formatea bytes como texto legible (1536 -> '1.5 KB')."""
    valor = float(num_bytes)
    for unidad in ("B", "KB", "MB", "GB"):
        if abs(valor) < 1024:
            return f"{valor:.1f} {unidad}"
        valor /= 1024
    return f"{valor:.1f} TB"


def formato_desde_nombre(nombre: str, por_defecto: str = "PNG") -> str:
    """Deduce el formato de Pillow a partir de la extensión del archivo."""
    ext = Path(nombre).suffix.lstrip(".").upper()
    return ALIAS_EXTENSION.get(ext, por_defecto)


def calcular_tamano(
    tamano: tuple[int, int],
    modo: str,
    ancho: int = 0,
    alto: int = 0,
    porcentaje: int = 100,
) -> tuple[int, int]:
    """Calcula el tamaño destino. Función pura: no toca la imagen."""
    w, h = tamano
    if modo == SIN_CAMBIOS:
        return w, h
    if modo == PORCENTAJE:
        factor = porcentaje / 100
        return max(1, round(w * factor)), max(1, round(h * factor))
    if modo == ANCHO_MAXIMO:
        if ancho <= 0 or w <= ancho:
            return w, h
        return ancho, max(1, round(h * ancho / w))
    if modo == DIMENSIONES_EXACTAS:
        return max(1, ancho), max(1, alto)
    return w, h


def redimensionar(img: Image.Image, opciones: OpcionesProceso) -> Image.Image:
    destino = calcular_tamano(
        img.size, opciones.modo_resize, opciones.ancho, opciones.alto, opciones.porcentaje
    )
    if destino == img.size:
        return img
    return img.resize(destino, Image.Resampling.LANCZOS)


def adaptar_modo(
    img: Image.Image, formato: str, fondo: tuple[int, int, int] = (255, 255, 255)
) -> Image.Image:
    """
    Convierte el modo de color al que el formato destino sabe escribir.

    Si el destino no soporta alfa (JPEG, BMP) la transparencia se aplana sobre
    `fondo` en vez de perderse de golpe.
    """
    soportados = MODOS_SOPORTADOS.get(formato)
    if soportados is None or img.mode in soportados:
        return img

    tiene_alfa = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    formato_con_alfa = "RGBA" in soportados

    if tiene_alfa and not formato_con_alfa:
        rgba = img.convert("RGBA")
        plano = Image.new("RGB", rgba.size, fondo)
        plano.paste(rgba, mask=rgba.split()[-1])
        return plano
    if tiene_alfa and formato_con_alfa:
        return img.convert("RGBA")
    return img.convert("RGB")


def _opciones_guardado(formato: str, opciones: OpcionesProceso, origen: Image.Image) -> dict:
    kwargs: dict = {}
    if formato in FORMATOS_CON_CALIDAD:
        kwargs["quality"] = opciones.calidad
        kwargs["optimize"] = True
    if formato == "JPEG":
        # Progresivo: mismo peso o menor y mejor render percibido en web.
        kwargs["progressive"] = True
    elif formato == "PNG":
        kwargs["optimize"] = True
        kwargs["compress_level"] = 9
    elif formato == "WEBP":
        kwargs["lossless"] = opciones.webp_sin_perdida
        kwargs["method"] = 6
    elif formato == "TIFF":
        kwargs["compression"] = "tiff_deflate"

    if opciones.conservar_metadatos:
        icc = origen.info.get("icc_profile")
        if icc:
            kwargs["icc_profile"] = icc
        exif = origen.info.get("exif")
        if exif and formato in ("JPEG", "WEBP", "TIFF", "PNG"):
            kwargs["exif"] = exif
    return kwargs


def _miniatura(img: Image.Image, lado: int = LADO_MINIATURA) -> bytes:
    """PNG pequeño para previsualizar sin cargar el original completo en RAM."""
    copia = img.copy()
    copia.thumbnail((lado, lado), Image.Resampling.LANCZOS)
    if copia.mode not in ("RGB", "RGBA", "L"):
        copia = copia.convert("RGBA" if "A" in copia.mode else "RGB")
    buffer = io.BytesIO()
    copia.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def procesar_imagen(
    datos: bytes,
    nombre: str,
    opciones: OpcionesProceso | None = None,
    *,
    con_miniaturas: bool = True,
) -> ResultadoImagen:
    """Convierte / comprime / redimensiona una imagen y devuelve el resultado."""
    opciones = opciones or OpcionesProceso()
    if not datos:
        raise ErrorImagen("El archivo está vacío")

    try:
        origen = Image.open(io.BytesIO(datos))
        origen.load()
    except Exception as exc:  # noqa: BLE001 - Pillow lanza tipos muy variados
        raise ErrorImagen(f"No se pudo abrir la imagen: {exc}") from exc

    ancho_px, alto_px = origen.size
    if ancho_px * alto_px > LIMITE_PIXELES:
        raise ErrorImagen(
            f"La imagen es demasiado grande ({ancho_px}x{alto_px} px). "
            f"Límite: {LIMITE_PIXELES // 1_000_000} MP"
        )

    # Aplica la rotación declarada en EXIF: sin esto las fotos de móvil salen tumbadas.
    img = ImageOps.exif_transpose(origen) or origen
    dimension_original = img.size
    miniatura_original = _miniatura(img) if con_miniaturas else b""

    formato = opciones.formato or origen.format or formato_desde_nombre(nombre)
    if formato not in EXTENSION_SALIDA:
        raise ErrorImagen(f"Formato de salida no soportado: {formato}")

    img = redimensionar(img, opciones)
    img = adaptar_modo(img, formato)

    buffer = io.BytesIO()
    try:
        img.save(buffer, format=formato, **_opciones_guardado(formato, opciones, origen))
    except Exception as exc:  # noqa: BLE001
        raise ErrorImagen(f"No se pudo guardar como {formato}: {exc}") from exc
    salida = buffer.getvalue()

    return ResultadoImagen(
        nombre=f"{Path(nombre).stem}{opciones.sufijo}.{EXTENSION_SALIDA[formato]}",
        datos=salida,
        formato=formato,
        mime=MIME[formato],
        peso_original=len(datos),
        peso_final=len(salida),
        dimension_original=dimension_original,
        dimension_final=img.size,
        miniatura_original=miniatura_original,
        miniatura_final=_miniatura(img) if con_miniaturas else b"",
    )


def procesar_lote(
    archivos: Iterable[tuple[str, bytes]],
    opciones: OpcionesProceso | None = None,
    progreso: Callable[[int, int, str], None] | None = None,
    *,
    con_miniaturas: bool = True,
) -> ResultadoLote:
    """
    Procesa varias imágenes. Un fallo individual no corta el lote: se acumula
    en `errores` y el resto sigue.
    """
    archivos = list(archivos)
    total = len(archivos)
    lote = ResultadoLote()
    for i, (nombre, datos) in enumerate(archivos, start=1):
        try:
            lote.resultados.append(procesar_imagen(datos, nombre, opciones, con_miniaturas=con_miniaturas))
        except ErrorImagen as exc:
            lote.errores.append((nombre, str(exc)))
        except Exception as exc:  # noqa: BLE001 - red de seguridad del lote
            lote.errores.append((nombre, f"Error inesperado: {exc}"))
        if progreso:
            progreso(i, total, nombre)
    return lote


def nombres_unicos(nombres: Sequence[str]) -> list[str]:
    """Evita que dos archivos con el mismo nombre se pisen dentro del ZIP."""
    vistos: dict[str, int] = {}
    salida: list[str] = []
    for nombre in nombres:
        clave = nombre.lower()
        if clave not in vistos:
            vistos[clave] = 1
            salida.append(nombre)
            continue
        ruta = Path(nombre)
        while True:
            vistos[clave] += 1
            candidato = f"{ruta.stem}_{vistos[clave]}{ruta.suffix}"
            if candidato.lower() not in vistos:
                vistos[candidato.lower()] = 1
                salida.append(candidato)
                break
    return salida


def crear_zip(resultados: Sequence[ResultadoImagen]) -> bytes:
    """Empaqueta los resultados en un ZIP en memoria."""
    buffer = io.BytesIO()
    nombres = nombres_unicos([r.nombre for r in resultados])
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for nombre, resultado in zip(nombres, resultados, strict=True):
            zf.writestr(nombre, resultado.datos)
    return buffer.getvalue()
