from pathlib import Path


def pasta_area_trabalho() -> Path:
    """Pasta da area de trabalho (Desktop), com fallbacks comuns no Windows."""
    home = Path.home()
    candidatos = [
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        home / "Área de Trabalho",
        home / "OneDrive" / "Área de Trabalho",
    ]
    for p in candidatos:
        if p.is_dir():
            return p
    return Path.cwd()
