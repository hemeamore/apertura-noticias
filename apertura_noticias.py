#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Oct  8 23:54:19 2025

@author: alvarocandia
"""

# -*- coding: utf-8 -*-
"""
Apertura de Noticias (solo titulares)
Temas: Plan México, Banca de Desarrollo, Sectores Productivos
Guarda archivos diarios en ~/aperturas/YYYY-MM-DD/apertura_noticias_D_Mes.md
Autor: Mr. PC + Jazz
"""

import os, time, re, requests, pytz, feedparser, pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from urllib.parse import quote_plus
from pathlib import Path

# =========================
# CONFIGURACIÓN
# =========================
TZ = "America/Mexico_City"
OUT_DIR_ROOT = os.path.join(os.path.expanduser("~"), "aperturas")
NOMBRE_BASE = "apertura_noticias"
NOMBRE_CSV_LOG = "apertura_noticias_log.csv"

MAX_POR_TEMA = 4
DAYS_BACK = 1
REINTENTOS = 3
ESPERA_SEG = 1.5

# --- Email ---
ASUNTO_BASE = "Apertura de noticias"
EMAIL_TO = ["alvarocandia007@gmail.com"]     # <<-- CAMBIA: destinatario(s)
EMAIL_CC = []                             # opcional
GMAIL_USER = os.getenv("GMAIL_USER")      # definido en apertura_auto.sh
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASS")

TEMAS = {
    "Plan México": [
        '“Plan México”', 'Plan Mexico', 'Polos de Bienestar', 'relocalización industrial México'
    ],
    "Banca de Desarrollo": [
        'banca de desarrollo México', 'Nafin', 'Bancomext', 'FIRA', 'Financiera Nacional de Desarrollo'
    ],
    "Sectores Productivos": [
        'sectores productivos México', 'industria manufacturera México',
        'nearshoring México', 'inversión productiva México'
    ]
}

HL = "es-419"; GL = "MX"; CEID = "MX:es-419"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) NewsBot/1.0"}
MESES_ES = {1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",
            7:"julio",8:"agosto",9:"septiembre",10:"octubre",
            11:"noviembre",12:"diciembre"}

# =========================
# FUNCIONES
# =========================
def ahora_tz():
    return datetime.now(pytz.timezone(TZ))

def ahora_str():
    return ahora_tz().strftime("%Y-%m-%d (%A) %H:%M %Z")

def construir_query(terminos, days_back=DAYS_BACK):
    return f"({' OR '.join(terminos)}) when:{days_back}d"

def google_news_rss(query):
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl={HL}&gl={GL}&ceid={CEID}"

def dominio(link):
    m = re.search(r"https?://([^/]+)/?", link)
    return m.group(1).replace("www.", "") if m else ""

def recortar(texto, n=160):
    if not texto: return ""
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto if len(texto) <= n else texto[:n-1] + "…"

def fetch_feed(url, reintentos=REINTENTOS, espera=ESPERA_SEG):
    last_exc = None
    for i in range(reintentos):
        try:
            resp = requests.get(url, headers=UA, timeout=20)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if getattr(feed, "entries", None):
                return feed
        except Exception as e:
            last_exc = e
        time.sleep(espera * (i+1))
    print(f"[WARN] RSS vacío/falló: {url} ({last_exc})")
    return None

def recoger_titulares_por_tema():
    todo = []
    for tema, terminos in TEMAS.items():
        q1 = construir_query(terminos)
        q2 = "(" + " OR ".join(terminos) + ")"
        feeds = [fetch_feed(google_news_rss(q)) for q in (q1, q2)]
        feed = next((f for f in feeds if f), None)
        if not feed:
            continue
        vistos = set(); capturados = []
        for entry in feed.entries:
            titulo = entry.get("title", "").strip()
            link = entry.get("link", "")
            sumry = recortar(entry.get("summary", ""))
            dom = dominio(link)
            key = (titulo.lower(), dom.lower())
            if key in vistos: continue
            vistos.add(key)
            capturados.append({
                "tema": tema,
                "titulo": titulo,
                "resumen": sumry,
                "link": link,
                "dominio": dom,
                "fecha_local": ahora_str()
            })
            if len(capturados) >= MAX_POR_TEMA:
                break
        todo.extend(capturados)
    return todo

def armar_markdown(fecha_str, items):
    lines = [f"# Apertura de noticias — {fecha_str}\n", "_Titulares automáticos (solo noticias)._", ""]
    df = pd.DataFrame(items)
    if df.empty:
        lines.append("> No se encontraron noticias para los filtros de hoy.")
        return "\n".join(lines)
    for tema in TEMAS.keys():
        sub = df[df["tema"] == tema]
        if sub.empty: continue
        lines.append(f"## {tema}")
        for _, r in sub.iterrows():
            lines.append(f"- **{r['titulo']}** — {recortar(r['resumen'], 180)} [Leer]({r['link']}) _(Fuente: {r['dominio']})_")
        lines.append("")
    return "\n".join(lines)

def guardar_salida_diaria(texto, out_root=OUT_DIR_ROOT, nombre_base=NOMBRE_BASE):
    os.makedirs(out_root, exist_ok=True)
    ahora = ahora_tz()
    carpeta_dia = os.path.join(out_root, ahora.strftime("%Y-%m-%d"))
    os.makedirs(carpeta_dia, exist_ok=True)
    dia = int(ahora.strftime("%d"))
    mes = MESES_ES[int(ahora.strftime("%m"))]
    nombre_archivo = f"{nombre_base}_{dia}_{mes}.md"
    ruta = os.path.join(carpeta_dia, nombre_archivo)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"[OK] Archivo diario guardado en: {ruta}")
    return ruta, carpeta_dia

def anexar_log(items, out_root=OUT_DIR_ROOT, nombre=NOMBRE_CSV_LOG):
    if not items: return None
    os.makedirs(out_root, exist_ok=True)
    ruta = os.path.join(out_root, nombre)
    df = pd.DataFrame(items)
    if os.path.exists(ruta):
        cur = pd.read_csv(ruta)
        pd.concat([cur, df], ignore_index=True).drop_duplicates(
            subset=["tema","titulo","link"], keep="first"
        ).to_csv(ruta, index=False)
    else:
        df.to_csv(ruta, index=False)
    return ruta

# ---------- Email ----------
def enviar_correo_con_md(ruta_md, fecha_str, cuerpo_preview=""):
    """Envía el .md por correo usando SMTP de Gmail (credenciales desde entorno)."""
    if not GMAIL_USER or not GMAIL_APP_PASS:
        print("[WARN] GMAIL_USER/GMAIL_APP_PASS no están definidos. No se envía correo.")
        return False

    # Lee el .md (cuerpo y adjunto)
    with open(ruta_md, "r", encoding="utf-8") as f:
        contenido_md = f.read()

    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(EMAIL_TO)
    if EMAIL_CC:
        msg["Cc"] = ", ".join(EMAIL_CC)
    msg["Subject"] = f"{ASUNTO_BASE} — {fecha_str}"

    cuerpo = f"""Hola, Mr. PC:

Apertura generada automáticamente.

{cuerpo_preview.strip()}
"""
    msg.attach(MIMEText(cuerpo + "\n\n" + contenido_md, "plain", "utf-8"))

    # Adjunta el .md
    part = MIMEBase("application", "octet-stream")
    with open(ruta_md, "rb") as f:
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(ruta_md)}"')
    msg.attach(part)

    # Envío
    dests = EMAIL_TO + EMAIL_CC
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASS)
        s.sendmail(GMAIL_USER, dests, msg.as_string())
    print("[OK] Correo enviado a:", dests)
    return True

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    fecha = ahora_str()
    items = recoger_titulares_por_tema()
    md = armar_markdown(fecha, items)
    md_path, carpeta_dia = guardar_salida_diaria(md)
    log_path = anexar_log(items)
    print("[OK] Resumen generado:")
    print("-", md_path)
    print("-", log_path or "(sin log)")

    # Marca de verificación de que todo terminó bien
    Path(carpeta_dia, ".ok").write_text("ok", encoding="utf-8")

    # Envío por email (si hay credenciales en el entorno)
    preview = f"Total notas capturadas: {len(items)}"
    enviar_correo_con_md(md_path, fecha, cuerpo_preview=preview)