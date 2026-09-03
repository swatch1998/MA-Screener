# M&A Screener

Screener financiero para research de M&A. Busca una empresa por ticker o nombre
y muestra su cuenta de resultados, balance, cash flow y ratios/múltiplos,
obtenidos en vivo de [yfinance](https://github.com/ranaroussi/yfinance)
(sin base de datos, sin cron — fetch bajo demanda con caché de 15 min).

## Estructura

- `data_fetcher.py` — capa de datos: descarga y cachea (`st.cache_data`, TTL 15 min)
  los estados financieros y ratios de un ticker, y resuelve nombre de empresa → ticker.
- `app.py` — frontend Streamlit: buscador, cabecera, expanders por tipología de
  estado financiero, toggle anual/trimestral e indicador de última actualización.

## Ejecutar en local

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
streamlit run app.py
```

Abre http://localhost:8501.

## Despliegue en Streamlit Community Cloud (gratis)

1. **Sube el proyecto a GitHub.**
   ```bash
   git init
   git add data_fetcher.py app.py requirements.txt README.md
   git commit -m "Initial M&A screener"
   git branch -M main
   git remote add origin https://github.com/<tu-usuario>/<tu-repo>.git
   git push -u origin main
   ```

2. **Crea la app en Streamlit Cloud.**
   - Ve a https://share.streamlit.io y entra con tu cuenta de GitHub.
   - Clic en "New app".
   - Selecciona el repositorio, la rama (`main`) y el archivo principal (`app.py`).
   - Clic en "Deploy".

3. **Streamlit Cloud instala automáticamente** las dependencias de
   `requirements.txt` y publica la app en una URL tipo
   `https://<tu-app>.streamlit.app`.

4. **Actualizaciones**: cada `git push` a la rama desplegada relanza la app
   automáticamente.

### Notas de despliegue

- No se necesita ninguna clave de API: yfinance consulta datos públicos de
  Yahoo Finance.
- Si yfinance empieza a dar errores de rate limit en producción (tráfico alto),
  el TTL de caché de 15 min (`CACHE_TTL_SECONDS` en `data_fetcher.py`) amortigua
  la mayoría de picos; puedes subirlo si hace falta.
- Streamlit Community Cloud "duerme" las apps sin tráfico tras un tiempo de
  inactividad; el primer acceso tras dormir tarda unos segundos en despertar.
