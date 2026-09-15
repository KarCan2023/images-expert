"""Tests de la lógica de procesamiento (no requieren Streamlit)."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from image_tools import (
    ANCHO_MAXIMO,
    DIMENSIONES_EXACTAS,
    PORCENTAJE,
    SIN_CAMBIOS,
    ErrorImagen,
    OpcionesProceso,
    adaptar_modo,
    calcular_tamano,
    crear_zip,
    formato_desde_nombre,
    humano,
    nombres_unicos,
    procesar_imagen,
    procesar_lote,
)


def imagen_bytes(formato="PNG", size=(120, 60), modo="RGB", color=(200, 30, 30), **kwargs) -> bytes:
    img = Image.new(modo, size, color)
    buffer = io.BytesIO()
    img.save(buffer, format=formato, **kwargs)
    return buffer.getvalue()


def abrir(datos: bytes) -> Image.Image:
    return Image.open(io.BytesIO(datos))


# ---------------- helpers puros ----------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [(0, "0.0 B"), (512, "512.0 B"), (1536, "1.5 KB"), (1024 * 1024, "1.0 MB")],
)
def test_humano(entrada, esperado):
    assert humano(entrada) == esperado


@pytest.mark.parametrize(
    ("nombre", "esperado"),
    [
        ("foto.jpg", "JPEG"),
        ("foto.JPEG", "JPEG"),
        ("escaneo.tif", "TIFF"),  # antes rompía: "TIF" no es un formato de Pillow
        ("logo.png", "PNG"),
        ("sin_extension", "PNG"),
    ],
)
def test_formato_desde_nombre(nombre, esperado):
    assert formato_desde_nombre(nombre) == esperado


@pytest.mark.parametrize(
    ("modo", "kwargs", "esperado"),
    [
        (SIN_CAMBIOS, {}, (800, 400)),
        (PORCENTAJE, {"porcentaje": 50}, (400, 200)),
        (PORCENTAJE, {"porcentaje": 150}, (1200, 600)),
        (ANCHO_MAXIMO, {"ancho": 400}, (400, 200)),
        (ANCHO_MAXIMO, {"ancho": 1600}, (800, 400)),  # no agranda
        (DIMENSIONES_EXACTAS, {"ancho": 100, "alto": 100}, (100, 100)),
    ],
)
def test_calcular_tamano(modo, kwargs, esperado):
    assert calcular_tamano((800, 400), modo, **kwargs) == esperado


def test_calcular_tamano_nunca_devuelve_cero():
    assert calcular_tamano((10, 4), PORCENTAJE, porcentaje=10) == (1, 1)


# ---------------- conversión de formato ----------------


def test_png_a_jpeg():
    r = procesar_imagen(imagen_bytes("PNG"), "foto.png", OpcionesProceso(formato="JPEG"))
    assert r.nombre == "foto_procesado.jpg"
    assert r.mime == "image/jpeg"
    assert abrir(r.datos).format == "JPEG"


def test_mantener_formato_original():
    r = procesar_imagen(imagen_bytes("WEBP"), "foto.webp", OpcionesProceso(formato=None))
    assert abrir(r.datos).format == "WEBP"


def test_transparencia_se_aplana_en_jpeg():
    datos = imagen_bytes("PNG", modo="RGBA", color=(255, 0, 0, 0))
    r = procesar_imagen(datos, "logo.png", OpcionesProceso(formato="JPEG"))
    salida = abrir(r.datos)
    assert salida.mode == "RGB"
    assert salida.getpixel((0, 0)) == (255, 255, 255)  # fondo blanco, no negro


def test_rgba_a_bmp_no_revienta():
    # Antes: OSError "cannot write mode RGBA as BMP".
    datos = imagen_bytes("PNG", modo="RGBA", color=(0, 128, 255, 128))
    r = procesar_imagen(datos, "x.png", OpcionesProceso(formato="BMP"))
    assert abrir(r.datos).format == "BMP"


def test_paleta_a_webp():
    datos = imagen_bytes("PNG", modo="P")
    r = procesar_imagen(datos, "x.png", OpcionesProceso(formato="WEBP"))
    assert abrir(r.datos).format == "WEBP"


def test_tif_de_entrada_se_mantiene():
    r = procesar_imagen(imagen_bytes("TIFF"), "escaneo.tif", OpcionesProceso(formato=None))
    assert abrir(r.datos).format == "TIFF"
    assert r.nombre == "escaneo_procesado.tiff"


def test_adaptar_modo_deja_intacto_lo_compatible():
    img = Image.new("RGB", (4, 4))
    assert adaptar_modo(img, "JPEG") is img


# ---------------- resize ----------------


def test_resize_por_porcentaje():
    r = procesar_imagen(
        imagen_bytes(size=(200, 100)), "x.png", OpcionesProceso(modo_resize=PORCENTAJE, porcentaje=50)
    )
    assert r.dimension_final == (100, 50)
    assert r.dimension_original == (200, 100)


def test_ancho_maximo_mantiene_proporcion():
    r = procesar_imagen(
        imagen_bytes(size=(1000, 500)),
        "x.png",
        OpcionesProceso(modo_resize=ANCHO_MAXIMO, ancho=400),
    )
    assert r.dimension_final == (400, 200)


# ---------------- EXIF / metadatos ----------------


def test_orientacion_exif_se_aplica():
    # Orientation = 6 -> la imagen debe girar 90°, quedando 60x120.
    exif = Image.Exif()
    exif[274] = 6
    datos = imagen_bytes("JPEG", size=(120, 60), exif=exif.tobytes())
    r = procesar_imagen(datos, "foto.jpg", OpcionesProceso(formato="JPEG"))
    assert r.dimension_final == (60, 120)


def test_metadatos_se_pueden_descartar():
    exif = Image.Exif()
    exif[271] = "Marca"
    datos = imagen_bytes("JPEG", exif=exif.tobytes())
    con = procesar_imagen(datos, "f.jpg", OpcionesProceso(formato="JPEG", conservar_metadatos=True))
    sin = procesar_imagen(datos, "f.jpg", OpcionesProceso(formato="JPEG", conservar_metadatos=False))
    assert abrir(con.datos).getexif().get(271) == "Marca"
    assert abrir(sin.datos).getexif().get(271) is None


# ---------------- calidad y peso ----------------


def test_menor_calidad_pesa_menos():
    datos = imagen_bytes("PNG", size=(400, 400))
    alta = procesar_imagen(datos, "x.png", OpcionesProceso(formato="JPEG", calidad=95))
    baja = procesar_imagen(datos, "x.png", OpcionesProceso(formato="JPEG", calidad=20))
    assert baja.peso_final < alta.peso_final


def test_ahorro_se_calcula_bien():
    datos = imagen_bytes("PNG", size=(300, 300))
    r = procesar_imagen(datos, "x.png", OpcionesProceso(formato="JPEG", calidad=30))
    assert r.ahorro == pytest.approx(100 * (1 - r.peso_final / r.peso_original))


# ---------------- errores ----------------


def test_archivo_corrupto():
    with pytest.raises(ErrorImagen):
        procesar_imagen(b"esto no es una imagen", "roto.png")


def test_archivo_vacio():
    with pytest.raises(ErrorImagen):
        procesar_imagen(b"", "vacio.png")


def test_opciones_invalidas():
    with pytest.raises(ValueError):
        OpcionesProceso(calidad=0)
    with pytest.raises(ValueError):
        OpcionesProceso(formato="GIF")
    with pytest.raises(ValueError):
        OpcionesProceso(modo_resize="inventado")


# ---------------- lote y ZIP ----------------


def test_lote_continua_tras_un_fallo():
    archivos = [("ok.png", imagen_bytes()), ("roto.png", b"xxx"), ("ok2.png", imagen_bytes())]
    lote = procesar_lote(archivos, OpcionesProceso(formato="JPEG"))
    assert len(lote.resultados) == 2
    assert [n for n, _ in lote.errores] == ["roto.png"]
    assert lote.peso_original == sum(r.peso_original for r in lote.resultados)


def test_lote_reporta_progreso():
    llamadas: list[tuple[int, int, str]] = []
    procesar_lote(
        [("a.png", imagen_bytes()), ("b.png", imagen_bytes())],
        None,
        lambda hechos, total, nombre: llamadas.append((hechos, total, nombre)),
    )
    assert [(h, t) for h, t, _ in llamadas] == [(1, 2), (2, 2)]


def test_lote_vacio():
    lote = procesar_lote([])
    assert lote.resultados == [] and lote.ahorro == 0.0


def test_nombres_unicos():
    assert nombres_unicos(["a.jpg", "a.jpg", "a.jpg", "b.jpg"]) == [
        "a.jpg",
        "a_2.jpg",
        "a_3.jpg",
        "b.jpg",
    ]


def test_zip_no_pierde_archivos_con_mismo_nombre():
    # Dos carpetas distintas pueden traer "foto.jpg": antes uno pisaba al otro.
    lote = procesar_lote(
        [("foto.png", imagen_bytes()), ("foto.png", imagen_bytes(color=(0, 0, 255)))],
        OpcionesProceso(formato="JPEG"),
    )
    with zipfile.ZipFile(io.BytesIO(crear_zip(lote.resultados))) as zf:
        assert zf.namelist() == ["foto_procesado.jpg", "foto_procesado_2.jpg"]


def test_miniaturas():
    r = procesar_imagen(imagen_bytes(size=(2000, 1000)), "x.png")
    assert abrir(r.miniatura_original).size == (480, 240)
    sin = procesar_imagen(imagen_bytes(), "x.png", con_miniaturas=False)
    assert sin.miniatura_original == b""
