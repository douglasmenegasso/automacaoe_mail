"""Configurações e utilidades compartilhadas do projeto."""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config(path: str | None = None) -> dict:
    """Carrega config.json (ou o caminho informado)."""
    cfg_path = path or os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(cfg_path):
        example = os.path.join(BASE_DIR, "config.example.json")
        raise FileNotFoundError(
            f"Arquivo {cfg_path} não encontrado. "
            f"Copie {example} para config.json e ajuste os valores."
        )
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)
