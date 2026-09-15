"""
Conversor de Imágenes - App local en Streamlit
Convierte formato, comprime y redimensiona imágenes (una o en lote).

Instalación:
    pip install streamlit pillow

Ejecutar:
    streamlit run app.py
"""

import io
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image

st.set_page_config(page_title="Conversor de Imágenes", page_icon="🖼️", layout="wide")

FORMATOS = {
    "Mantener original": None,
    "JPG": "JPEG",
    "PNG": "PNG",
    "WEBP": "WEBP",
    "BMP": "BMP",
    "TIFF": "TIFF",
}

FORMATOS_CON_CALIDAD = {"JPEG", "WEBP"}


def humano(num_bytes: int) -> str:
    for unidad in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unidad}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def redimensionar(img: Image.Image, modo: str, ancho: int, alto: int, porcentaje: int) -> Image.Image:
    if modo == "Sin cambios":
        return img
    w, h = img.size
    if modo == "Porcentaje":
        factor = porcentaje / 100
        nuevo = (max(1, int(w * factor)), max(1, int(h * factor)))
    elif modo == "Ancho máximo (mantiene proporción)":
        if w <= ancho:
            return img
        factor = ancho / w
        nuevo = (ancho, max(1, int(h * factor)))
    elif modo == "Dimensiones exactas":
        nuevo = (ancho, alto)
    else:
        return img
    return img.resize(nuevo, Image.LANCZOS)


def procesar_imagen(archivo, formato_salida, calidad, modo_resize, ancho, alto, porcentaje):
    img = Image.open(archivo)
    img_original = img.copy()

    # Formato de salida
    ext_original = (archivo.name.rsplit(".", 1)[-1] if "." in archivo.name else "png").upper()
    ext_original = "JPEG" if ext_original in ("JPG", "JPEG") else ext_original
    pil_formato = formato_salida or ext_original

    # PNG/otros con transparencia -> convertir a RGB si el destino es JPEG
    if pil_formato == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        fondo = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    elif img.mode == "P":
        img = img.convert("RGBA")

    # Resize
    img = redimensionar(img, modo_resize, ancho, alto, porcentaje)

    # Guardar en buffer
    buffer = io.BytesIO()
    kwargs = {}
    if pil_formato in FORMATOS_CON_CALIDAD:
        kwargs["quality"] = calidad
        kwargs["optimize"] = True
    elif pil_formato == "PNG":
        kwargs["optimize"] = True

    img.save(buffer, format=pil_formato, **kwargs)
    buffer.seek(0)

    nombre_base = Path(archivo.name).stem
    ext_final = "jpg" if pil_formato == "JPEG" else pil_formato.lower()
    nombre_salida = f"{nombre_base}_procesado.{ext_final}"

    return {
        "nombre": nombre_salida,
        "bytes": buffer.getvalue(),
        "peso_original": archivo.size,
        "peso_final": len(buffer.getvalue()),
        "preview_original": img_original,
        "preview_final": img,
    }


# ---------------- UI ----------------

st.title("🖼️ Conversor de Imágenes")
st.caption("Convierte formato, comprime y redimensiona imágenes — todo en local, sin subir nada a internet.")

with st.sidebar:
    st.header("⚙️ Opciones")

    st.subheader("Formato de salida")
    formato_label = st.selectbox("Convertir a:", list(FORMATOS.keys()), index=1)
    formato_salida = FORMATOS[formato_label]

    st.subheader("Compresión")
    calidad = st.slider(
        "Calidad (solo aplica a JPG/WEBP)",
        min_value=10,
        max_value=100,
        value=80,
        step=5,
        help="Menor calidad = menor peso de archivo",
    )

    st.subheader("Redimensionar")
    modo_resize = st.radio(
        "Modo:",
        ["Sin cambios", "Porcentaje", "Ancho máximo (mantiene proporción)", "Dimensiones exactas"],
    )

    ancho = alto = porcentaje = 0
    if modo_resize == "Porcentaje":
        porcentaje = st.slider("Porcentaje del tamaño original", 10, 200, 100, step=10)
    elif modo_resize == "Ancho máximo (mantiene proporción)":
        ancho = st.number_input("Ancho máximo (px)", min_value=50, value=1200, step=50)
    elif modo_resize == "Dimensiones exactas":
        col1, col2 = st.columns(2)
        ancho = col1.number_input("Ancho (px)", min_value=10, value=800, step=10)
        alto = col2.number_input("Alto (px)", min_value=10, value=600, step=10)

st.divider()

archivos = st.file_uploader(
    "Sube una o varias imágenes",
    type=["png", "jpg", "jpeg", "webp", "bmp", "tiff"],
    accept_multiple_files=True,
)

if archivos:
    if st.button("🚀 Procesar imágenes", type="primary"):
        resultados = []
        barra = st.progress(0, text="Procesando...")
        for i, archivo in enumerate(archivos):
            try:
                resultado = procesar_imagen(
                    archivo, formato_salida, calidad, modo_resize, ancho, alto, porcentaje
                )
                resultados.append(resultado)
            except Exception as e:
                st.error(f"Error procesando {archivo.name}: {e}")
            barra.progress((i + 1) / len(archivos))
        barra.empty()

        if resultados:
            st.success(f"✅ {len(resultados)} imagen(es) procesada(s)")

            peso_total_original = sum(r["peso_original"] for r in resultados)
            peso_total_final = sum(r["peso_final"] for r in resultados)
            ahorro = 100 * (1 - peso_total_final / peso_total_original) if peso_total_original else 0

            col1, col2, col3 = st.columns(3)
            col1.metric("Peso original total", humano(peso_total_original))
            col2.metric("Peso final total", humano(peso_total_final))
            col3.metric("Ahorro", f"{ahorro:.1f}%")

            # Descarga en lote (ZIP) si hay más de una imagen
            if len(resultados) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for r in resultados:
                        zf.writestr(r["nombre"], r["bytes"])
                zip_buffer.seek(0)
                st.download_button(
                    "⬇️ Descargar todas (ZIP)",
                    data=zip_buffer,
                    file_name="imagenes_procesadas.zip",
                    mime="application/zip",
                    type="primary",
                )

            st.divider()

            for r in resultados:
                with st.expander(f"{r['nombre']} — {humano(r['peso_original'])} → {humano(r['peso_final'])}"):
                    c1, c2 = st.columns(2)
                    c1.image(r["preview_original"], caption="Original", use_container_width=True)
                    c2.image(r["preview_final"], caption="Procesada", use_container_width=True)
                    st.download_button(
                        f"⬇️ Descargar {r['nombre']}",
                        data=r["bytes"],
                        file_name=r["nombre"],
                        mime="image/*",
                        key=f"dl_{r['nombre']}",
                    )
else:
    st.info("👆 Sube al menos una imagen para comenzar.")
