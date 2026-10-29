# amigable-mef

Un servidor MCP que le da a Claude acceso a la **Consulta Amigable del MEF**: el presupuesto (PIA, PIM) y la
ejecución (certificación, compromiso, devengado, girado) del gasto público del Perú, de los tres niveles de
gobierno, desde 2012. Además trae las **definiciones oficiales de los clasificadores presupuestarios**, para que
quien no conoce los filtros sepa dónde cae cada gasto.

La Consulta Amigable no tiene API: el servidor repite los clics de la web (agrupar, elegir una fila, volver a
agrupar) y lee la tabla. Las cuentas las hace Python, así que cada cifra sale de una consulta que se puede repetir
en la web.

## Qué trae

| Primitiva | Nombre | Para qué |
|---|---|---|
| Herramienta | `consultar` | Una tabla de la Consulta Amigable: agrupar por nivel de gobierno, sector, pliego, municipalidad, función, programa, genérica, fuente, departamento, mes... siguiendo una ruta de filtros |
| Herramienta | `resumen` | Total, promedio, mediana, máximo, mínimo, ranking con participación %, avance % y brecha PIM − devengado |
| Herramienta | `barrido` | La misma consulta en varios años, con la variación año a año |
| Herramienta | `glosario` | Busca en los clasificadores del MEF qué significa una partida, fuente o rubro, y cómo filtrarla |
| Recurso | `amigable://glosario/columnas` | Qué es PIA, PIM, certificación, devengado, girado, avance % |
| Recurso | `amigable://clasificador/{clasificador}/{codigo}` | La ficha de una partida con su definición y sus partidas hijas |
| Prompt | `consulta(pregunta)` | Traduce una pregunta a la ruta de filtros y obliga a citar año, ruta y fuente |

## Uso

Necesitan [`uv`](https://docs.astral.sh/uv/), internet y Claude Code.

```bash
uv run pytest -q                 # las pruebas, con datos reales de la Consulta Amigable
claude                           # en esta carpeta: .mcp.json ya conecta amigable-mef y fetch
```

En Claude Code:

- `/mcp` muestra `amigable-mef` y `fetch` conectados.
- *«¿Cuánto ejecutó la Municipalidad de Lima en seguridad ciudadana en 2025?»*
- `@amigable-mef:amigable://clasificador/gasto/2.3` para la ficha de bienes y servicios.
- `/mcp__amigable-mef__consulta presupuesto de carreteras en Cajamarca 2020-2024`

Las consultas se guardan en `datos/cache/` (git la ignora). Los años cerrados quedan guardados; el año en curso se
vuelve a pedir al día siguiente, porque cambia a diario.

## La evaluación

`evaluar.py` le hace las 10 preguntas de `preguntas.csv` a Claude con `claude -p`, sin herramientas, con búsqueda
web y con este MCP, y las califica contra la cifra oficial. `grafico.py` dibuja `grafico.png` desde
`resultados.csv`. El análisis está en [`informe.md`](informe.md).

```bash
uv run evaluar.py --modos memoria web mcp      # unos 5 minutos con Haiku
uv run grafico.py
```

## El glosario

`glosario.csv` sale de los PDF oficiales de los
[clasificadores presupuestarios del MEF](https://www.mef.gob.pe/es/clasificadores-presupuestarios) del año
fiscal 2026: el clasificador económico de gastos (924 partidas) y el de fuentes de financiamiento y rubros. Para
regenerarlo:

```bash
uv run construir_glosario.py
```

## Límites conocidos

Cuando una pregunta pide un detalle que la fuente no tiene, el servidor le indica a Claude que lo diga, dé la cifra
del nivel más cercano explicando qué incluye y ofrezca la alternativa sin ejecutarla hasta que el usuario la pida.

- La vista «¿Dónde se gasta?» llega a departamento, no a provincia ni distrito. La alternativa para una provincia
  es el gasto de sus municipalidades, que deja fuera lo que gastan ahí el Gobierno Nacional y el regional.
- Algunos temas no tienen un programa propio. El dengue, por ejemplo, está dentro del programa 0017, que cubre
  todas las enfermedades metaxénicas y zoonosis.
- La página tiene protección contra bots: el servidor espera 0.7 s entre pedidos y reintenta si no recibe datos.
