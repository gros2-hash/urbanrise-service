import os
import base64
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import slugify

# ========= CONFIGURACIÓN =========

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # viene de las Environment Variables de Render
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_TOKEN no está definido en las variables de entorno")

GITHUB_USER = "gros2-hash"
REPO_NAME = "urbanrise-fichas"
LOGO_URL = "https://static.tokkobroker.com/tfw_images/14240_URBANRISE/logo_urban_naranja.jpg"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    )
}

# *** ESTA ES LA INSTANCIA QUE UVICORN NECESITA ***
app = FastAPI(title="UrbanRise Fichas Service")


# ========= MODELO REQUEST =========

class CrearFichaRequest(BaseModel):
    url: str
    slug: str | None = None


# ========= SCRAPER BASE (REMAX) =========

def scrapear_propiedad_remax(url_anuncio: str) -> dict:
    resp = requests.get(url_anuncio, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # ----- TÍTULO -----
    titulo_el = soup.find("h1")
    titulo = titulo_el.get_text(strip=True) if titulo_el else "Propiedad UrbanRise"

    # ----- PRECIO (selector genérico, luego se afina) -----
    precio_el = soup.select_one("[class*=price], [class*=precio]")
    precio = precio_el.get_text(strip=True) if precio_el else "No especificado"

    # ----- UBICACIÓN -----
    ubic_el = soup.select_one("[class*=location], [class*=ubicacion], [class*=address]")
    ubicacion = ubic_el.get_text(strip=True) if ubic_el else "No especificada"

    # ----- DESCRIPCIÓN -----
    desc_el = soup.select_one(
        "div[class*=description], div[class*=descripcion], section[class*=description]"
    )
    if desc_el:
        descripcion = " ".join(desc_el.get_text(separator=" ", strip=True).split())
    else:
        descripcion = "Descripción no disponible en el portal."

    # ----- IMÁGENES -----
    imagenes: list[str] = []

    posibles_galerias = soup.select(
        "div[class*='gallery'], div[class*='carousel'], "
        "div[class*='slider'], div[class*='photos']"
    )
    if posibles_galerias:
        gal = posibles_galerias[0]
        for img in gal.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy") or img.get("src")
            if not src:
                continue
            src_abs = urljoin(url_anuncio, src)
            if any(x in src_abs.lower() for x in ["logo", "icon", "placeholder", "avatar"]):
                continue
            if src_abs not in imagenes:
                imagenes.append(src_abs)

    if not imagenes:
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            src_abs = urljoin(url_anuncio, src)
            if any(x in src_abs.lower() for x in ["logo", "icon", "placeholder", "avatar"]):
                continue
            if src_abs not in imagenes:
                imagenes.append(src_abs)

    imagenes = imagenes[:12]

    datos = {
        "OPERACION": "Alquiler",
        "TIPO": "Casa",
        "TITULO": titulo,
        "UBICACION": ubicacion,
        "PRECIO": precio,
        "SUPERFICIE": "No especificado",
        "DORMITORIOS_AMBIENTES": "No especificado",
        "BANIOS": "No especificado",
        "COCHERA": "No especificado",
        "ESTADO": "No especificado",
        "EXPENSAS": "No especificado",
        "DESTACADOS": "No especificado",
        "ANIO_CONSTRUCCION": "No especificado",
        "PISOS": "No especificado",
        "ORIENTACION": "No especificado",
        "MASCOTAS": "No especificado",
        "MOBILIARIO": "No especificado",
        "DESCRIPCION": descripcion,
        "IMAGENES": imagenes,
    }

    return datos


# ========= GENERACIÓN HTML =========

def generar_html(datos: dict) -> str:
    template_path = Path("ficha_template.html")
    if not template_path.exists():
        raise RuntimeError("No se encuentra ficha_template.html en el directorio del servicio.")

    template = template_path.read_text(encoding="utf-8")

    galeria_html = ""
    for url in datos.get("IMAGENES", []):
        galeria_html += f'<img src="{url}" alt="Foto de la propiedad">\n'

    html = template.format(
        LOGO_URL=LOGO_URL,
        GALERIA_IMAGENES=galeria_html,
        **datos
    )
    return html


# ========= SUBIDA A GITHUB =========

def subir_a_github(html: str, slug: str) -> str:
    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/contents/fichas/{slug}.html"

    message = f"Crear/actualizar ficha {slug}"
    content = base64.b64encode(html.encode("utf-8")).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    resp_get = requests.get(api_url, headers=headers)
    data = {"message": message, "content": content}

    if resp_get.status_code == 200:
        sha = resp_get.json().get("sha")
        if sha:
            data["sha"] = sha

    resp_put = requests.put(api_url, headers=headers, data=json.dumps(data))
    if resp_put.status_code not in (200, 201):
        raise RuntimeError(f"Error subiendo a GitHub: {resp_put.status_code} {resp_put.text}")

    url_publica = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/fichas/{slug}.html"
    return url_publica


# ========= ENDPOINT =========

@app.post("/crear-ficha")
def crear_ficha(payload: CrearFichaRequest):
    try:
        datos = scrapear_propiedad_remax(payload.url)
        slug = payload.slug or slugify.slugify(datos["TITULO"]) or "propiedad-urbanrise"
        html = generar_html(datos)
        url_ficha = subir_a_github(html, slug)
        return {
            "ok": True,
            "slug": slug,
            "url_ficha": url_ficha,
            "imagenes": datos.get("IMAGENES", []),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========= RUN LOCAL (opcional) =========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
