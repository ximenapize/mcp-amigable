"""Servidor MCP de la Consulta Amigable del MEF: presupuesto y ejecución del gasto público del Perú.

    uv run pytest -q                                                  # las pruebas, con datos reales
    uv run server.py                                                  # el servidor, por stdio
    claude mcp add --scope project mcp-amigable -- uv run server.py   # conectarlo a Claude Code

La Consulta Amigable no tiene API: es una página ASP.NET que se recorre con postbacks. Este servidor repite los
clics (agrupar por un criterio, elegir una fila, agrupar por el siguiente) y lee la tabla. Las cuentas las hace
Python, no el modelo: así cada cifra sale de una consulta que se puede repetir en la web.
"""
import hashlib
import html
import json
import re
import threading
import time
import unicodedata
from datetime import date
from functools import cache
from pathlib import Path

import httpx
import pandas as pd
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

AQUI = Path(__file__).parent
CACHE = AQUI / "datos" / "cache"
GLOSARIO = AQUI / "glosario.csv"      # lo arma construir_glosario.py desde los clasificadores del MEF
NAVEGADOR = "https://apps5.mineco.gob.pe/transparencia/Navegador/"
SOLO_LECTURA = {"readOnlyHint": True, "openWorldHint": True}
PAUSA = 0.7          # segundos entre pedidos: la página tiene protección contra bots
MODOS = {"todo": "ActProy", "actividades": "Actividad", "proyectos": "Proyecto"}

# El botón de cada criterio se llama ctl00$CPH1$Btn<Nombre>. Estos son los nombres legibles de los conocidos;
# los que no estén aquí se usan en minúsculas (BtnFoo -> "foo").
CRITERIOS = {
    "TipoGobierno": "nivel_gobierno", "SubTipoGobierno": "gobierno_local", "Sector": "sector",
    "Pliego": "pliego", "Ejecutora": "ejecutora", "Departamento": "departamento_gl", "Provincia": "provincia_gl",
    "Municipalidad": "municipalidad", "Mancomunidad": "mancomunidad", "ProgramaPpto": "categoria_presupuestal",
    "ProdProy": "producto_proyecto", "AAO": "actividad", "Funcion": "funcion",
    "DivFuncional": "division_funcional", "GrupoFuncional": "grupo_funcional", "FuenteAgregada": "fuente",
    "Rubro": "rubro", "Generica": "generica", "SubGenerica": "subgenerica", "SubGenericaDetalle": "subgenerica_detalle",
    "Especifica": "especifica", "EspecificaDetalle": "especifica_detalle", "DepartamentoMeta": "departamento",
    "ProvinciaMeta": "provincia", "DistritoMeta": "distrito", "Trimestre": "trimestre", "Mes": "mes",
}
MONTOS = ["pia", "pim", "compromiso_anual", "atencion_compromiso_mensual", "devengado", "girado", "certificacion"]

mcp = FastMCP("mcp-amigable", instructions=(
    "Presupuesto y ejecución del gasto público del Perú (Gobierno Nacional, regional y local) desde la Consulta "
    "Amigable del MEF. Usa consultar para recorrer la información como en la web: agrupa por un criterio, elige "
    "una fila por su código y vuelve a agrupar. No sumes ni calcules porcentajes a mano: las herramientas ya los "
    "devuelven. Cita siempre el año, la ruta y la fuente de cada cifra. Si la pregunta pide un detalle que la "
    "Consulta Amigable no tiene (una provincia por ubicación, una enfermedad sin programa propio), no la cambies "
    "por otra en silencio: dilo, da la cifra del nivel más cercano que sí existe explicando qué incluye, y ofrece "
    "las alternativas sin ejecutarlas hasta que el usuario las pida."))

_candado = threading.Lock()
_ultimo_pedido = 0.0


def _criterio(boton):
    return CRITERIOS.get(boton, boton.lower())


def _boton(criterio):
    inverso = {v: k for k, v in CRITERIOS.items()}
    return inverso.get(criterio, criterio[:1].upper() + criterio[1:])


def _campos(pagina):
    """Los campos ocultos del formulario (__VIEWSTATE y compañía) que hay que devolver en cada postback."""
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', pagina))


def _botones(pagina):
    return dict(re.findall(r'name="ctl00\$CPH1\$Btn([A-Za-z0-9]+)" value="([^"]+)"', pagina))


def _filas(pagina):
    """Cada fila trae en su radio el código y los montos con decimales: código/PIA/PIM/compromiso anual/
    atención de compromiso mensual/devengado/girado/certificación. El nombre está en la celda de al lado."""
    filas = []
    for valor, texto in re.findall(r'name="grp1" value="([^"]+)".*?<td align="left"[^>]*>\s*(.*?)\s*</td>',
                                   pagina, flags=re.S):
        partes = valor.split("/")
        nombre = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", texto))).strip()
        fila = {"codigo": partes[0].strip(), "nombre": nombre.split(": ", 1)[-1], "_radio": valor}
        fila |= {m: round(float(x or 0), 2) for m, x in zip(MONTOS, partes[1:])}   # años viejos traen vacíos
        fila["avance_pct"] = round(100 * fila["devengado"] / fila["pim"], 1) if fila["pim"] else None
        filas.append(fila)
    return filas


def _pedir(cliente, metodo, url, **kw):
    """Un pedido con pausa entre llamadas y reintentos si la página responde algo que no es el navegador."""
    global _ultimo_pedido
    for intento in range(4):
        with _candado:
            espera = PAUSA - (time.time() - _ultimo_pedido)
            if espera > 0:
                time.sleep(espera)
            try:
                r = cliente.request(metodo, url, **kw)
            except httpx.HTTPError:
                r = None
            _ultimo_pedido = time.time()
        if r is not None and r.status_code == 200 and "__VIEWSTATE" in r.text:
            return r
        time.sleep(3 * (intento + 1))
    raise ToolError("La Consulta Amigable no respondió con datos. Esperen unos segundos y vuelvan a intentar.")


def _navegar(anio, modo, ruta, agrupar_por):
    """Repite los clics de la web: por cada paso de la ruta agrupa por su criterio y elige la fila de su código;
    al final agrupa por agrupar_por. Devuelve la página final y la URL de inicio."""
    if modo not in MODOS:
        raise ToolError(f"modo debe ser uno de {list(MODOS)}, no {modo!r}.")
    with httpx.Client(follow_redirects=True, timeout=60) as c:
        r = _pedir(c, "GET", NAVEGADOR + "Navegar.aspx", params={"y": anio, "ap": MODOS[modo]})
        url = str(r.url)
        pasos = [(p["criterio"], p["codigo"]) for p in ruta] + [(agrupar_por, None)]
        seleccion = None
        for criterio, codigo in pasos:
            botones = _botones(r.text)
            if _boton(criterio) not in botones:
                disponibles = [_criterio(b) for b in botones]
                raise ToolError(f"No se puede agrupar por {criterio!r} en este punto de la ruta. "
                                f"Opciones: {disponibles}")
            datos = _campos(r.text)
            if seleccion:
                datos["grp1"] = seleccion
            datos["ctl00$CPH1$Btn" + _boton(criterio)] = botones[_boton(criterio)]
            r = _pedir(c, "POST", url, data=datos)
            if codigo is not None:
                filas = _filas(r.text)
                elegida = next((f for f in filas if f["codigo"] == str(codigo).strip()), None)
                if elegida is None:
                    ejemplos = ", ".join(f"{f['codigo']} ({f['nombre']})" for f in filas[:8])
                    raise ToolError(f"No hay una fila con código {codigo!r} al agrupar por {criterio!r} en {anio}. "
                                    f"Algunas que sí hay: {ejemplos}")
                seleccion = elegida["_radio"]
        return r.text, url


def _archivo_cache(*clave):
    return CACHE / (hashlib.sha1(json.dumps(clave, ensure_ascii=False).encode()).hexdigest() + ".json")


@mcp.tool(annotations=SOLO_LECTURA)
def consultar(anio: int, agrupar_por: str, ruta: list[dict] | None = None, modo: str = "todo") -> dict:
    """Presupuesto (PIA, PIM) y ejecución (certificación, compromiso, devengado, girado, avance %) del gasto
    público, agrupado por un criterio, como en la Consulta Amigable del MEF.

    Úsala para cualquier cifra del gasto: cuánto tiene o gastó un nivel de gobierno, sector, pliego,
    municipalidad, función, genérica, fuente o departamento, en un año desde 2012.

    - agrupar_por: "nivel_gobierno", "sector", "pliego", "ejecutora", "gobierno_local", "funcion", "generica",
      "fuente", "rubro", "departamento", "categoria_presupuestal", "mes", "trimestre", etc. La respuesta dice en
      `puede_agrupar_por` qué criterios siguen disponibles.
    - ruta: las filas elegidas antes, en orden, cada una {"criterio", "codigo"}. Ejemplo, los pliegos del sector
      Interior: ruta=[{"criterio": "nivel_gobierno", "codigo": "E"}, {"criterio": "sector", "codigo": "07"}],
      agrupar_por="pliego". Los códigos salen de una consulta anterior.
    - modo: "todo" (actividades y proyectos), "actividades" o "proyectos".

    El devengado es lo que efectivamente se gastó; el avance % es devengado / PIM. Al agrupar por genérica,
    subgenérica, fuente o rubro, cada fila trae también su definición oficial del clasificador del MEF.
    """
    return _consultar(anio, agrupar_por, ruta or [], modo)


def _consultar(anio, agrupar_por, ruta, modo):
    archivo = _archivo_cache(anio, modo, ruta, agrupar_por)
    vigente = anio >= date.today().year      # el año en curso cambia a diario: la caché dura hasta mañana
    if archivo.exists():
        guardado = json.loads(archivo.read_text())
        if not vigente or guardado["consultado"] == date.today().isoformat():
            return guardado | {"desde_cache": True}

    pagina, url = _navegar(anio, modo, ruta, agrupar_por)
    filas = _filas(pagina)
    for f in filas:
        del f["_radio"]
        if partida := _partida_de_fila(agrupar_por, f["codigo"]):
            f["definicion"] = partida["definicion"]
    total = {m: round(sum(f[m] for f in filas), 2) for m in MONTOS}
    total["avance_pct"] = round(100 * total["devengado"] / total["pim"], 1) if total["pim"] else None
    respuesta = {
        "anio": anio, "modo": modo, "ruta": ruta, "agrupado_por": agrupar_por, "filas": filas, "total": total,
        "puede_agrupar_por": [_criterio(b) for b in _botones(pagina)],
        "unidad": "soles", "consultado": date.today().isoformat(), "fuente": url,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    archivo.write_text(json.dumps(respuesta, ensure_ascii=False))
    return respuesta | {"desde_cache": False}


@mcp.tool(annotations=SOLO_LECTURA)
def resumen(anio: int, agrupar_por: str, ruta: list[dict] | None = None, monto: str = "devengado",
            top: int = 10, modo: str = "todo") -> dict:
    """Estadísticas de una consulta, ya calculadas: total, número de filas, promedio, mediana, máximo, mínimo,
    ranking con la participación % de cada fila, avance % y brecha PIM − devengado (lo que falta gastar).

    Úsala en vez de sumar o comparar filas a mano: "¿qué municipalidad de Lima gastó más?", "¿qué parte del
    presupuesto de Salud es bienes y servicios?", "¿cuál es el avance promedio de los pliegos del sector?".
    Recibe los mismos agrupar_por, ruta y modo que consultar. monto: "pia", "pim", "certificacion",
    "compromiso_anual", "devengado" o "girado". top: cuántas filas lleva el ranking.
    """
    if monto not in MONTOS:
        raise ToolError(f"monto debe ser uno de {MONTOS}, no {monto!r}.")
    datos = _consultar(anio, agrupar_por, ruta or [], modo)
    filas = datos["filas"]
    if not filas:
        raise ToolError("La consulta no devolvió filas: revisen la ruta con consultar.")
    serie = pd.Series([f[monto] for f in filas])
    total = serie.sum()

    def ficha(f):
        return {"codigo": f["codigo"], "nombre": f["nombre"], "valor": f[monto], "avance_pct": f["avance_pct"],
                "participacion_pct": round(100 * f[monto] / total, 2) if total else None}

    ordenadas = sorted(filas, key=lambda f: f[monto], reverse=True)
    avances = pd.Series([f["avance_pct"] for f in filas if f["avance_pct"] is not None])
    return {
        "anio": anio, "ruta": datos["ruta"], "agrupado_por": agrupar_por, "monto": monto, "unidad": "soles",
        "n": len(filas), "total": round(total, 2), "promedio": round(serie.mean(), 2),
        "mediana": round(serie.median(), 2), "maximo": ficha(ordenadas[0]), "minimo": ficha(ordenadas[-1]),
        "ranking": [ficha(f) for f in ordenadas[:top]],
        "avance_pct": datos["total"]["avance_pct"],
        "avance_promedio_de_las_filas": round(avances.mean(), 1) if len(avances) else None,
        "filas_con_avance_menor_a_50": [f["nombre"] for f in filas if (f["avance_pct"] or 0) < 50],
        "brecha_pim_devengado": round(datos["total"]["pim"] - datos["total"]["devengado"], 2),
        "fuente": datos["fuente"],
    }


@mcp.tool(annotations=SOLO_LECTURA)
def barrido(anios: list[int], agrupar_por: str, ruta: list[dict] | None = None, monto: str = "pim",
            modo: str = "todo") -> dict:
    """La misma consulta en varios años, con la variación año a año ya calculada: para tendencias como "¿cómo
    cambió el presupuesto de carreteras en Cajamarca de 2020 a 2024?" o "¿cuánto creció el programa 0017 en
    los últimos cinco años?".

    Recibe los mismos agrupar_por, ruta y modo que consultar, y la lista de años (máximo 15). Devuelve, por año,
    el PIA, PIM, devengado y avance % del total; la serie del monto elegido con su variación % año a año y entre
    el primer y el último año; y una tabla con el monto de cada fila (por código) en cada año. Si una ruta no
    existe en algún año (los códigos cambian), ese año queda con su error y el resto sigue.
    Cada año son varios pedidos a la Consulta Amigable: la primera vez puede tardar medio minuto.
    """
    if monto not in MONTOS:
        raise ToolError(f"monto debe ser uno de {MONTOS}, no {monto!r}.")
    if not 1 <= len(anios) <= 15:
        raise ToolError("Pidan entre 1 y 15 años.")
    por_anio, tabla, fuentes = [], {}, {}
    for anio in sorted(anios):
        try:
            datos = _consultar(anio, agrupar_por, ruta or [], modo)
        except ToolError as e:
            por_anio.append({"anio": anio, "error": str(e)})
            continue
        t = datos["total"]
        por_anio.append({"anio": anio, "pia": t["pia"], "pim": t["pim"], "devengado": t["devengado"],
                         "avance_pct": t["avance_pct"]})
        for f in datos["filas"]:
            tabla.setdefault(f["codigo"], {"nombre": f["nombre"]})[str(anio)] = f[monto]
        fuentes[anio] = datos["fuente"]
    serie = [(a["anio"], a[monto]) for a in por_anio if "error" not in a]
    variaciones = [{"de": a, "a": b, "variacion_pct": round(100 * (vb - va) / va, 1) if va else None,
                    "cambio": round(vb - va, 2)} for (a, va), (b, vb) in zip(serie, serie[1:])]
    primero, ultimo = (serie[0], serie[-1]) if serie else (None, None)
    return {
        "agrupado_por": agrupar_por, "ruta": ruta or [], "monto": monto, "unidad": "soles", "por_anio": por_anio,
        "variacion_anual": variaciones,
        "variacion_total_pct": round(100 * (ultimo[1] - primero[1]) / primero[1], 1)
        if serie and primero[1] else None,
        "filas_por_anio": [{"codigo": c} | v for c, v in tabla.items()],
        "fuente": fuentes,
    }


# --- Glosario: las definiciones oficiales de los clasificadores presupuestarios -------------------------------

FASES = {
    "PIA": "Presupuesto Institucional de Apertura: el presupuesto inicial de la entidad, aprobado con la Ley de "
           "Presupuesto del año.",
    "PIM": "Presupuesto Institucional Modificado: el PIA más las modificaciones del año (créditos "
           "suplementarios, transferencias, habilitaciones). Es el presupuesto vigente.",
    "Certificación": "Acto que garantiza que hay crédito presupuestario disponible y libre de afectación para "
                     "un gasto, antes de comprometerlo.",
    "Compromiso anual": "Afectación preventiva del presupuesto por el monto de una obligación que se ejecutará "
                        "en el año (por ejemplo, un contrato firmado).",
    "Atención de compromiso mensual": "La parte del compromiso anual que se programa ejecutar en el mes.",
    "Devengado": "Reconocimiento de la obligación de pago, después de verificar que el bien, servicio u obra se "
                 "entregó. Es la medida habitual de cuánto se gastó.",
    "Girado": "Emisión del pago (cheque, transferencia) por una obligación devengada.",
    "Avance %": "Devengado / PIM × 100: qué parte del presupuesto vigente ya se gastó.",
}


def _sin_tildes(s):
    return unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode()


@cache
def _glosario():
    df = pd.read_csv(GLOSARIO, dtype=str).fillna("")
    df["texto"] = (df.nombre + " " + df.definicion).map(_sin_tildes)
    return df


def _partida(clasificador, codigo):
    df = _glosario()
    fila = df[(df.clasificador == clasificador) & (df.codigo == codigo)]
    return fila.iloc[0].drop("texto").to_dict() if len(fila) else None


def _partida_de_fila(criterio, codigo):
    """La partida del clasificador que corresponde a una fila de la Consulta Amigable. Allí la genérica 2.3 se
    escribe 5-2-3 (el 5 es la categoría de gasto: 5 corriente, 6 capital, 7 deuda) y la subgenérica 2.3.1, 2-3-1."""
    if criterio in ("fuente", "rubro"):
        return _partida(criterio, codigo)
    if criterio.startswith(("generica", "subgenerica", "especifica")):
        partes = codigo.split("-")
        if criterio == "generica":
            partes = partes[1:]
        return _partida("gasto", ".".join(str(int(p)) for p in partes if p.isdigit()))
    return None


@mcp.tool(annotations={"readOnlyHint": True})
def glosario(texto: str = "", codigo: str = "", clasificador: str = "", limite: int = 10) -> dict:
    """Qué significa cada partida del gasto, cada fuente de financiamiento y cada rubro, con la definición
    oficial del MEF. Úsala cuando alguien no sabe dónde cae un gasto o qué filtro elegir en consultar.

    Ejemplos: texto="viáticos", texto="mantenimiento de carreteras", texto="canon", codigo="2.3.2.7".
    clasificador: "gasto", "fuente" o "rubro" (vacío: todos). Todas las palabras de texto deben aparecer en el
    nombre o la definición. Cada resultado dice cómo filtrarlo en consultar. También devuelve qué significa
    cada columna de la Consulta Amigable (PIA, PIM, devengado...).
    """
    df = _glosario()
    m = pd.Series(True, index=df.index)
    if clasificador:
        m &= df.clasificador == clasificador
    if codigo:
        m &= df.codigo.str.startswith(codigo.strip())
    for palabra in _sin_tildes(texto).split():
        m &= df.texto.str.contains(re.escape(palabra))
    sel = df[m].assign(en_nombre=lambda d: d.nombre.map(_sin_tildes).str.contains(_sin_tildes(texto)),
                       nivel_num=lambda d: d.codigo.str.count(r"\."))
    sel = sel.sort_values(["en_nombre", "nivel_num"], ascending=[False, True]).head(limite)
    resultados = [r.drop(["texto", "en_nombre", "nivel_num"]).to_dict() | {"como_filtrar": _como_filtrar(r)}
                  for _, r in sel.iterrows()]
    return {"resultados": resultados, "total_encontrados": int(m.sum()), "columnas": FASES}


def _como_filtrar(r):
    if r.clasificador in ("fuente", "rubro"):
        return f'consultar(agrupar_por="{r.clasificador}") y elegir el código {r.codigo}'
    partes = r.codigo.split(".")
    if len(partes) < 2:
        return "Es el total del gasto: no hace falta filtrar."
    niveles = ["generica", "subgenerica", "subgenerica_detalle", "especifica", "especifica_detalle"]
    criterio = niveles[len(partes) - 2]
    codigo_ca = "-".join(partes) if len(partes) > 2 else f"5-{partes[0]}-{partes[1]} (o 6-, 7- si es de capital o deuda)"
    return (f'agrupar_por="{criterio}" partiendo desde la genérica; en la Consulta Amigable su código es '
            f"{codigo_ca}")


@mcp.resource("amigable://glosario/columnas")
def columnas() -> dict:
    """Qué significa cada columna de la Consulta Amigable: PIA, PIM, certificación, compromiso, devengado..."""
    return FASES


@mcp.resource("amigable://clasificador/{clasificador}/{codigo}")
def ficha_partida(clasificador: str, codigo: str) -> dict:
    """La ficha de una partida: clasificador "gasto" (código 2.3.1.5.1.2), "fuente" (1 a 5) o "rubro" (00, 09...),
    con su nombre, nivel, definición oficial y las partidas que cuelgan de ella."""
    partida = _partida(clasificador, codigo)
    if partida is None:
        raise ToolError(f"No existe la partida {codigo!r} en el clasificador {clasificador!r}. Búsquenla con glosario.")
    df = _glosario()
    hijas = df[(df.clasificador == clasificador) & df.codigo.str.match(re.escape(codigo) + r"\.\d+$")]
    return partida | {"partidas_hijas": [f"{c}: {n}" for c, n in zip(hijas.codigo, hijas.nombre)]}


@mcp.prompt
def consulta(pregunta: str) -> str:
    """Responde una pregunta sobre el gasto público como lo haría alguien que conoce la Consulta Amigable:
    traduce la pregunta a una ruta de filtros, consulta y cita cada cifra."""
    return f"""Pregunta: {pregunta}

Respóndela con el servidor mcp-amigable, en este orden:

1. Traduce la pregunta a filtros de la Consulta Amigable. Piensa en sus cuatro preguntas:
   - ¿Quién gasta? nivel_gobierno (E nacional, R regional, M local) → sector → pliego, o para municipalidades
     nivel_gobierno M → gobierno_local M → departamento_gl → provincia_gl → municipalidad.
   - ¿En qué se gasta? funcion → division_funcional → grupo_funcional, o categoria_presupuestal (programas) →
     producto_proyecto → actividad, o generica → subgenerica (bienes y servicios, personal, obras...).
   - ¿Dónde se gasta? departamento. La web no baja a provincia ni distrito por ubicación.
   - ¿Con qué se financia? fuente → rubro.
   Si no sabes dónde cae un concepto, búscalo con glosario. Rutas que ya se sabe que funcionan:
   seguridad ciudadana = funcion 05 → division_funcional 014 → grupo_funcional 0031, o el programa 0030;
   carreteras = funcion 15 → division_funcional 033 (vías nacionales, departamentales y vecinales);
   dengue = programa 0017, que es de todas las enfermedades metaxénicas y zoonosis.
2. Si la pregunta pide un detalle que la Consulta Amigable no tiene, no la reemplaces por otra en silencio:
   - Dilo primero, en una línea: qué no existe en la fuente.
   - Da la cifra del nivel más cercano que sí existe y explica qué incluye. Por ejemplo, para una provincia, la
     del departamento («todo lo que se gasta en el departamento de Cajamarca, por los tres niveles de
     gobierno»); para el dengue, la del programa 0017 («presupuesto para dengue, malaria, leishmaniasis,
     Chagas, bartonelosis y zoonosis en conjunto: no se puede separar el dengue»).
   - Ofrece las alternativas sin ejecutarlas: para una provincia, el gasto de sus municipalidades (que deja
     fuera al Gobierno Nacional y al regional); para un tema, los productos o actividades del programa que más
     se le acercan. Solo cuando el usuario la pida, haz esa consulta.
3. Recorre la ruta con consultar, un paso a la vez: los códigos de cada paso salen de la respuesta anterior.
4. No hagas cuentas a mano: usa resumen para rankings, participaciones y promedios, y barrido para comparar años.
5. Responde con una tabla corta y, para cada cifra, el año, la ruta de filtros, si es PIA, PIM o devengado, y el
   link de la fuente. Si el año está en curso, aclara que la cifra cambia a diario."""


if __name__ == "__main__":
    mcp.run()
