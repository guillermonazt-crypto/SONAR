# sonar/web/app.py
#
# Autor: Guillermo Nazt
# Proyecto: SONAR - Sistema de Observabilidad de Nodos y Analisis de Red
#
# Interfaz web de onboarding para gestionar el inventario de switches.
# Permite agregar y eliminar dispositivos sin editar archivos YAML.

import sys
from pathlib import Path

# Add project root to sys.path to support running directly (e.g. python sonar/web/app.py)
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# pyrefly: ignore [missing-import]
from flask import Flask, render_template, request, redirect, url_for
import yaml

from sonar.utils.logger import get_logger

log = get_logger(__name__)
app = Flask(__name__)

Inventory_path = ROOT / "inventory" / "devices.yaml"

def leer_inventario() -> list:
    """
    Lee el inventario actual de devices.yaml.

    Returns:
        Lista de dispositivos o lista vacia si no existe el archivo.
    """
    if not Inventory_path.exists():
        return []

    with open(Inventory_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data:
        return []
    return data.get("devices", [])

def guardar_inventario(dispositivos: list) -> None:
    """
    Guarda la lista de dispositivos en devices.yaml.

    Args:
        dispositivos: Lista de dispositivos a guardar
    """
    with open(Inventory_path, "w", encoding="utf-8") as f:
        yaml.dump({"devices": dispositivos}, f, allow_unicode=True)

# ---------------------------------------------------------------------------
# Rutas de la aplicacion web
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """
    Pagina principal: muestra todos los switches del inventario.
    """
    devices = leer_inventario()
    return render_template("index.html", devices=devices)

@app.route("/agregar", methods=["POST"])
def agregar():
    """
    Recibe el formulario y agrega un nuevo switch al inventario.
    """
    devices = leer_inventario()

    nuevo = {
        "hostname": request.form.get("hostname", "").strip(),
        "name": request.form.get("name", "").strip(),
        "role": request.form.get("role", "").strip(),
        "site": request.form.get("site", "").strip()
    }

    # Validacion Basica
    if not nuevo["hostname"] or not nuevo["name"]:
        log.warning("Intento de agregar dispositivo sin hostname o nombre")
        return redirect(url_for("index"))

    # Verificar duplicados
    for d in devices:
        if d["hostname"].lower() == nuevo["hostname"].lower():
            log.warning(f"Intento de agregar duplicado: {nuevo['hostname']}")
            return redirect(url_for("index"))

    devices.append(nuevo)
    guardar_inventario(devices)

    log.info(f"Dispositivo agregado: {nuevo['hostname']}")
    return redirect(url_for("index"))

@app.route("/eliminar/<nombre>")
def eliminar(nombre: str):
    """
    Elimina un switch del inventario por su nombre.

    Args:
        nombre: Nombre del dispositivo a eliminar
    """
    devices = leer_inventario()
    devices = [d for d in devices if d.get('name', '').lower() != nombre.lower()]
    guardar_inventario(devices)

    log.info(f"Dispositivo eliminado: {nombre}")
    return redirect(url_for("index"))

if __name__ == "__main__":
    log.info("Iniciando interfaz web de SONAR en http://localhost:5000")
    app.run(debug=True, port=5000)