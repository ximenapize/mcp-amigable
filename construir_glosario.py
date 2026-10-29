"""Arma glosario.csv con las definiciones oficiales de los clasificadores presupuestarios del MEF.

    uv run construir_glosario.py

Baja los PDF del año (https://www.mef.gob.pe/es/clasificadores-presupuestarios), lee cada partida por la
posición de sus palabras en la página (código, nombre y definición van en columnas fijas) y escribe un CSV que
queda en el repositorio: el servidor lo lee sin necesitar internet ni librerías de PDF.
"""
import io
import re

import httpx
import pandas as pd
import pdfplumber

from server import GLOSARIO

PDF_GASTO = ("https://cdn.www.gob.pe/uploads/document/file/9212086/"
             "7562162-anexo-2-clasificador-economico-de-gastos-para-el-ano-fiscal-2026%282%29.pdf")
PDF_FUENTES = ("https://cdn.www.gob.pe/uploads/document/file/9212090/"
               "7562162-anexo-4-clasificador-de-fuentes-de-financiamiento-y-rubros-para-el-ano-fiscal-2026.pdf")
NIVELES_GASTO = {1: "tipo de transacción", 2: "genérica", 3: "subgenérica", 4: "subgenérica detalle",
                 5: "específica", 6: "específica detalle"}
TOLERANCIA = 3                        # palabras a menos de 3 puntos de altura van en el mismo renglón


def bajar(url):
    r = httpx.get(url, timeout=120, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return pdfplumber.open(io.BytesIO(r.content))


def lineas(pdf, bordes, encabezado):
    """Las palabras de cada renglón, separadas en columnas por los bordes dados (en puntos desde la izquierda).
    Se salta lo que está más arriba de `encabezado`: el membrete de cada página."""
    cortes = [0, *bordes, 10_000]
    for pagina in pdf.pages:
        renglones = []                 # el código y el nombre a veces quedan medio punto más arriba o abajo
        for w in sorted(pagina.extract_words(), key=lambda w: w["top"]):
            if w["top"] <= encabezado:
                continue
            if renglones and w["top"] - renglones[-1][0]["top"] <= TOLERANCIA:
                renglones[-1].append(w)
            else:
                renglones.append([w])
        for renglon in renglones:
            palabras = sorted(renglon, key=lambda w: w["x0"])
            yield [" ".join(w["text"] for w in palabras if a <= w["x0"] < b) for a, b in zip(cortes, cortes[1:])]


def limpiar(filas, url):
    for f in filas:
        f["nombre"] = re.sub(r"\s+", " ", f["nombre"]).strip(" .")
        f["definicion"] = re.sub(r"^[-*]\s*", "", re.sub(r"\s+", " ", f["definicion"]).strip())
        f["fuente"] = url
    return filas


def partidas_gasto(pdf):
    """Clasificador económico de gastos: código, nombre y definición en tres columnas."""
    filas = []
    for codigo, nombre, definicion in lineas(pdf, bordes=[82, 305], encabezado=90):
        if codigo:
            numeros = re.findall(r"\d+", codigo)
            filas.append({"clasificador": "gasto", "codigo": ".".join(numeros),
                          "nivel": NIVELES_GASTO.get(len(numeros), ""), "nombre": nombre, "definicion": definicion})
        elif filas:                    # renglón que sigue al anterior: el nombre o la definición no cupieron
            filas[-1]["nombre"] += " " + nombre if nombre else ""
            filas[-1]["definicion"] += " " + definicion if definicion else ""
    return filas


def partidas_fuentes(pdf):
    """Fuentes de financiamiento a la izquierda ("1. RECURSOS ORDINARIOS"); a la derecha sus rubros
    ("00. Recursos Ordinarios") con la definición en los renglones de abajo."""
    filas, fuente = [], None
    for izquierda, derecha in lineas(pdf, bordes=[250], encabezado=0):
        if m := re.match(r"(\d)\.\s*(.*)", izquierda):
            fuente = {"clasificador": "fuente", "codigo": m.group(1), "nivel": "fuente de financiamiento",
                      "nombre": m.group(2), "definicion": ""}
            filas.append(fuente)
        elif izquierda and fuente:     # el nombre de la fuente no cupo en un renglón
            fuente["nombre"] += " " + izquierda
        if m := re.match(r"(\d{2})\.\s+(.*)", derecha):
            filas.append({"clasificador": "rubro", "codigo": m.group(1), "nivel": "rubro", "nombre": m.group(2),
                          "definicion": "", "fuente_financiamiento": fuente["codigo"]})
        elif derecha and filas and filas[-1]["clasificador"] == "rubro":
            rubro = filas[-1]          # un renglón en minúscula antes de la definición sigue siendo el nombre
            rubro["nombre" if derecha[0].islower() and not rubro["definicion"] else "definicion"] += " " + derecha
    for f in filas:                    # la fuente se define por sus rubros
        if f["clasificador"] == "fuente":
            rubros = [r["nombre"] for r in filas if r.get("fuente_financiamiento") == f["codigo"]]
            f["definicion"] = "Fuente de financiamiento que agrupa los rubros: " + "; ".join(rubros) + "."
    return filas


if __name__ == "__main__":
    with bajar(PDF_GASTO) as pdf:
        filas = limpiar(partidas_gasto(pdf), PDF_GASTO)
    with bajar(PDF_FUENTES) as pdf:
        filas += limpiar(partidas_fuentes(pdf), PDF_FUENTES)
    df = pd.DataFrame(filas)
    df.to_csv(GLOSARIO, index=False)
    print(df.groupby(["clasificador", "nivel"]).size().to_string())
    print(f"{len(df)} partidas en {GLOSARIO.name}")
