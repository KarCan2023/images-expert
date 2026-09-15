"""
Conversor de Imágenes - App local en Streamlit
Convierte formato, comprime y redimensiona imágenes (una o en lote).

Instalación:
    pip install -r requirements.txt

Ejecutar:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from image_tools import (
    ANCHO_MAXIMO,
    DIMENSIONES_EXACTAS,
    FORMATOS,
    MODOS_RESIZE,
    PORCENTAJE,
    OpcionesProceso,
    ResultadoLote,
    crear_zip,
    humano,
    procesar_lote,
)

st.set_page_config(page_title="Conversor de Imágenes", page_icon="🖼️", layout="wide")

EXTENSIONES_ENTRADA = ["png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"]


def mostrar_imagen(contenedor, datos: bytes, caption: str) -> None:
    """st.image compatible con versiones antiguas y nuevas de Streamlit."""
    try:
        contenedor.image(datos, caption=caption, width="stretch")
    except Exception:  # noqa: BLE001 - API antigua (< 1.49)
        contenedor.image(datos, caption=caption, use_container_width=True)


def leer_opciones() -> OpcionesProceso:
    """Panel lateral. Devuelve las opciones elegidas."""
    with st.sidebar:
        st.header("⚙️ Opciones")

        st.subheader("Formato de salida")
        formato_label = st.selectbox("Convertir a:", list(FORMATOS.keys()), index=1)
        formato = FORMATOS[formato_label]

        st.subheader("Compresión")
        calidad = st.slider(
            "Calidad (solo aplica a JPG/WEBP)",
            min_value=10,
            max_value=100,
            value=80,
            step=5,
            help="Menor calidad = menor peso de archivo. 75-85 suele ser el punto dulce para web.",
        )
        webp_sin_perdida = False
        if formato == "WEBP":
            webp_sin_perdida = st.checkbox(
                "WEBP sin pérdida",
                value=False,
                help="Ignora la calidad y conserva todos los píxeles. Pesa más.",
            )

        st.subheader("Redimensionar")
        modo_resize = st.radio("Modo:", MODOS_RESIZE)

        ancho = alto = 0
        porcentaje = 100
        if modo_resize == PORCENTAJE:
            porcentaje = st.slider("Porcentaje del tamaño original", 10, 200, 100, step=10)
        elif modo_resize == ANCHO_MAXIMO:
            ancho = st.number_input("Ancho máximo (px)", min_value=50, value=1200, step=50)
        elif modo_resize == DIMENSIONES_EXACTAS:
            col1, col2 = st.columns(2)
            ancho = col1.number_input("Ancho (px)", min_value=10, value=800, step=10)
            alto = col2.number_input("Alto (px)", min_value=10, value=600, step=10)

        st.subheader("Avanzado")
        conservar_metadatos = st.checkbox(
            "Conservar metadatos (EXIF / perfil de color)",
            value=True,
            help="Desactívalo para quitar geolocalización y datos de cámara, y ahorrar algunos KB.",
        )
        sufijo = st.text_input("Sufijo del archivo de salida", value="_procesado")

    return OpcionesProceso(
        formato=formato,
        calidad=calidad,
        modo_resize=modo_resize,
        ancho=int(ancho),
        alto=int(alto),
        porcentaje=int(porcentaje),
        conservar_metadatos=conservar_metadatos,
        webp_sin_perdida=webp_sin_perdida,
        sufijo=sufijo,
    )


def ejecutar(archivos, opciones: OpcionesProceso) -> ResultadoLote:
    barra = st.progress(0.0, text="Procesando...")

    def avance(hechos: int, total: int, nombre: str) -> None:
        barra.progress(hechos / total, text=f"Procesando {nombre} ({hechos}/{total})")

    lote = procesar_lote(((archivo.name, archivo.getvalue()) for archivo in archivos), opciones, avance)
    barra.empty()
    return lote


def mostrar_resultados(lote: ResultadoLote) -> None:
    for nombre, error in lote.errores:
        st.error(f"Error procesando {nombre}: {error}")

    if not lote.resultados:
        return

    st.success(f"✅ {len(lote.resultados)} imagen(es) procesada(s)")

    col1, col2, col3 = st.columns(3)
    col1.metric("Peso original total", humano(lote.peso_original))
    col2.metric("Peso final total", humano(lote.peso_final))
    col3.metric(
        "Ahorro",
        f"{lote.ahorro:.1f}%",
        delta=f"-{humano(lote.peso_original - lote.peso_final)}"
        if lote.peso_final <= lote.peso_original
        else f"+{humano(lote.peso_final - lote.peso_original)}",
        delta_color="inverse",
    )

    if lote.peso_final > lote.peso_original:
        st.warning(
            "El resultado pesa más que el original. Baja la calidad, reduce el tamaño "
            "o prueba WEBP para bajar el peso."
        )

    if len(lote.resultados) > 1:
        st.download_button(
            "⬇️ Descargar todas (ZIP)",
            data=crear_zip(lote.resultados),
            file_name="imagenes_procesadas.zip",
            mime="application/zip",
            type="primary",
        )

    st.divider()

    for i, r in enumerate(lote.resultados):
        titulo = (
            f"{r.nombre} — {humano(r.peso_original)} → {humano(r.peso_final)} "
            f"({r.ahorro:+.1f}%) · {r.dimension_original[0]}×{r.dimension_original[1]} → "
            f"{r.dimension_final[0]}×{r.dimension_final[1]}"
        )
        with st.expander(titulo):
            c1, c2 = st.columns(2)
            mostrar_imagen(c1, r.miniatura_original, "Original")
            mostrar_imagen(c2, r.miniatura_final, "Procesada")
            st.download_button(
                f"⬇️ Descargar {r.nombre}",
                data=r.datos,
                file_name=r.nombre,
                mime=r.mime,
                key=f"dl_{i}_{r.nombre}",
            )


# ---------------- UI ----------------

st.title("🖼️ Conversor de Imágenes")
st.caption("Convierte formato, comprime y redimensiona imágenes — todo en local, sin subir nada a internet.")

opciones = leer_opciones()

st.divider()

archivos = st.file_uploader(
    "Sube una o varias imágenes",
    type=EXTENSIONES_ENTRADA,
    accept_multiple_files=True,
)

if archivos:
    if st.button("🚀 Procesar imágenes", type="primary"):
        # El resultado vive en session_state: sin esto, al pulsar un botón de
        # descarga Streamlit re-ejecuta el script y la vista se vacía.
        st.session_state["lote"] = ejecutar(archivos, opciones)
        st.session_state["opciones"] = opciones

    lote = st.session_state.get("lote")
    if lote:
        if st.session_state.get("opciones") != opciones:
            st.info("Cambiaste las opciones. Vuelve a procesar para aplicarlas.")
        mostrar_resultados(lote)
else:
    st.session_state.pop("lote", None)
    st.info("👆 Sube al menos una imagen para comenzar.")
