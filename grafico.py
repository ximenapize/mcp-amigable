"""Dibuja grafico.png: cuántas preguntas acierta, falla o dice no saber Claude en cada modo.

    uv run grafico.py
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

AQUI = Path(__file__).parent
RESULTADOS = ["acierta", "se equivoca", "no sabe"]
COLORES = {"acierta": "#0ca30c", "se equivoca": "#d03b3b", "no sabe": "#b4b2ab"}
MODOS = {"memoria": "Sin herramientas", "web": "Búsqueda web", "mcp": "MCP amigable-mef"}
TINTA, TENUE, FONDO = "#1f1f1d", "#898781", "#fcfcfb"

res = pd.read_csv(AQUI / "resultados.csv")
tabla = res.groupby("modo").resultado.value_counts().unstack(fill_value=0).reindex(
    index=list(MODOS)[::-1], columns=RESULTADOS, fill_value=0)
segundos = res.groupby("modo").segundos.mean()

fig, ax = plt.subplots(figsize=(8, 3.2), facecolor=FONDO)
ax.set_facecolor(FONDO)
izquierda = pd.Series(0, index=tabla.index)
for resultado in RESULTADOS:
    ancho = tabla[resultado]
    ax.barh([MODOS[m] for m in tabla.index], ancho, left=izquierda, height=0.55, color=COLORES[resultado],
            edgecolor=FONDO, linewidth=2, label=resultado)
    for i, (m, n) in enumerate(ancho.items()):
        if n:
            ax.text(izquierda[m] + n / 2, i, str(n), ha="center", va="center", fontsize=11,
                    color="white" if resultado != "no sabe" else TINTA, fontweight="bold")
    izquierda += ancho
for i, m in enumerate(tabla.index):
    ax.text(10.2, i, f"{segundos[m]:.0f} s por pregunta", va="center", fontsize=9, color=TENUE)

ax.set_xlim(0, 12.2)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, labelsize=11, labelcolor=TINTA)
for lado in ax.spines.values():
    lado.set_visible(False)
ax.set_title("De 10 preguntas sobre el gasto público, solo el MCP dio la cifra oficial",
             loc="left", fontsize=12, color=TINTA, pad=26)
ax.legend(ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=9, labelcolor=TINTA,
          handlelength=1, handleheight=1)
fig.text(0.01, 0.02, f"Claude Haiku con claude -p, {pd.Timestamp('today'):%d/%m/%Y}. "
         "Cifra oficial: Consulta Amigable del MEF (ver preguntas.csv).", fontsize=8, color=TENUE)
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig(AQUI / "grafico.png", dpi=200, facecolor=FONDO)
print(tabla.to_string())
