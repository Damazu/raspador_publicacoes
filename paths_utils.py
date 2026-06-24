import os
import shutil
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


def pasta_dados_app() -> Path:
    """Pasta gravavel e discreta para arquivos internos do app (sessoes, etc.)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".local" / "share"
    pasta = base / "raspador_social_media"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def caminho_estado_sessao(nome_arquivo: str) -> Path:
    """JSON de sessao do Playwright em pasta de dados do app (fora da Area de Trabalho)."""
    destino = pasta_dados_app() / nome_arquivo
    if destino.is_file():
        return destino

    for legado in (Path.cwd() / nome_arquivo, pasta_area_trabalho() / nome_arquivo):
        if legado.is_file():
            try:
                shutil.copy2(legado, destino)
            except OSError:
                pass
            break
    return destino
