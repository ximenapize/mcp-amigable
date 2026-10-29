"""El contrato del servidor: si estas pruebas pasan, Claude Code y evaluar.py pueden usarlo.

    uv run pytest -q

Llaman al servidor en memoria, igual que lo haría Claude Code, y piden datos reales a la Consulta Amigable.
Usan el año 2025, que ya cerró, para que las cifras no cambien de un día a otro.
"""
import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from server import mcp

NACIONAL = [{"criterio": "nivel_gobierno", "codigo": "E"}]
INTERIOR = NACIONAL + [{"criterio": "sector", "codigo": "07"}]
MUNICIPALIDADES_LIMA = [{"criterio": "nivel_gobierno", "codigo": "M"}, {"criterio": "gobierno_local", "codigo": "M"},
                        {"criterio": "departamento_gl", "codigo": "15"}, {"criterio": "provincia_gl", "codigo": "01"}]


async def _con_cliente(f):
    async with Client(mcp) as c:
        return await f(c)


def llamar(herramienta, **args):
    return asyncio.run(_con_cliente(lambda c: c.call_tool(herramienta, args))).data


def test_niveles_de_gobierno():
    r = llamar("consultar", anio=2025, agrupar_por="nivel_gobierno")
    assert {f["codigo"] for f in r["filas"]} == {"E", "M", "R"}
    assert r["total"]["pim"] == pytest.approx(sum(f["pim"] for f in r["filas"]))
    assert r["total"]["pim"] == pytest.approx(272_450_859_407, rel=1e-3)
    assert r["fuente"].startswith("https://apps5.mineco.gob.pe/transparencia/Navegador/")


def test_hijos_suman_el_padre():
    padre = next(f for f in llamar("consultar", anio=2025, agrupar_por="nivel_gobierno")["filas"] if f["codigo"] == "E")
    hijos = llamar("consultar", anio=2025, agrupar_por="sector", ruta=NACIONAL)
    assert hijos["total"]["pim"] == pytest.approx(padre["pim"], abs=1)
    assert hijos["total"]["devengado"] == pytest.approx(padre["devengado"], abs=1)


def test_ruta_hasta_una_municipalidad():
    r = llamar("consultar", anio=2025, agrupar_por="municipalidad", ruta=MUNICIPALIDADES_LIMA)
    lima = next(f for f in r["filas"] if f["codigo"] == "301250")
    assert "METROPOLITANA DE LIMA" in lima["nombre"]
    assert lima["avance_pct"] == pytest.approx(100 * lima["devengado"] / lima["pim"], abs=0.1)


def test_anio_viejo_con_montos_vacios():
    r = llamar("consultar", anio=2020, agrupar_por="provincia_gl", ruta=MUNICIPALIDADES_LIMA[:2] + [
        {"criterio": "departamento_gl", "codigo": "06"}])
    assert any(f["nombre"] == "CAJAMARCA" for f in r["filas"])


def test_codigo_inexistente_da_un_error_claro():
    with pytest.raises(ToolError, match="XX"):
        llamar("consultar", anio=2025, agrupar_por="pliego", ruta=NACIONAL + [{"criterio": "sector", "codigo": "XX"}])


def test_criterio_invalido_dice_las_opciones():
    with pytest.raises(ToolError, match="Opciones"):
        llamar("consultar", anio=2025, agrupar_por="color_favorito")


def test_segunda_consulta_sale_de_cache():
    llamar("consultar", anio=2025, agrupar_por="sector", ruta=NACIONAL)
    assert llamar("consultar", anio=2025, agrupar_por="sector", ruta=NACIONAL)["desde_cache"] is True


def test_resumen_sin_cuentas_a_mano():
    r = llamar("resumen", anio=2025, agrupar_por="pliego", ruta=INTERIOR, monto="pim")
    assert r["maximo"]["codigo"] == "007"
    assert sum(f["participacion_pct"] for f in r["ranking"]) <= 100.01
    assert {"total", "n", "promedio", "mediana", "minimo", "avance_pct", "brecha_pim_devengado"} <= r.keys()


def test_barrido_calcula_la_variacion():
    r = llamar("barrido", anios=[2024, 2025], agrupar_por="nivel_gobierno", monto="pim")
    pim = {a["anio"]: a["pim"] for a in r["por_anio"]}
    assert r["variacion_anual"][0]["variacion_pct"] == pytest.approx(100 * (pim[2025] - pim[2024]) / pim[2024], abs=0.1)


def test_glosario_explica_bienes_y_servicios():
    r = llamar("glosario", texto="bienes y servicios")
    item = next(i for i in r["resultados"] if i["codigo"] == "2.3")
    assert "ADQUISICIÓN DE BIENES" in item["definicion"].upper()
    assert item["fuente"].startswith("https://")


def test_cuatro_herramientas_como_minimo():
    herramientas = asyncio.run(_con_cliente(lambda c: c.list_tools()))
    assert len(herramientas) >= 4
    assert all(len(h.description or "") > 80 for h in herramientas), "cada herramienta necesita un buen docstring"


def test_un_recurso():
    async def contar(c):
        return len(await c.list_resources()) + len(await c.list_resource_templates())
    assert asyncio.run(_con_cliente(contar)) >= 1


def test_un_prompt():
    assert len(asyncio.run(_con_cliente(lambda c: c.list_prompts()))) >= 1
