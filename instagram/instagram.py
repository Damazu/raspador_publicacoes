import threading
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

INSTAGRAM_URL = "https://www.instagram.com/"
STORAGE_STATE = Path("instagram_state.json")


def clicar_curtidas(page, log_callback):
    seletores = [
        'a[href*="/liked_by/"]',
        'button:has-text("curtidas")',
        'button:has-text("Curtidas")',
        'a:has-text("curtidas")',
        'a:has-text("Curtidas")',
        'span:has-text("curtidas")',
        'span:has-text("Curtidas")',
        'a:has-text("likes")',
        'button:has-text("likes")',
    ]

    for seletor in seletores:
        alvo = page.locator(seletor).first
        try:
            if alvo.is_visible(timeout=1200):
                alvo.click()
                time.sleep(1)
                log_callback("Clique em curtidas executado.")
                return True
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    log_callback("ERRO: Nao encontrei um botao/link de curtidas visivel.")
    return False


class InstagramRunner:
    def __init__(self, log_callback, waiting_callback, finished_callback):
        self.log_callback = log_callback
        self.waiting_callback = waiting_callback
        self.finished_callback = finished_callback
        self._confirm_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._confirm_event.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def confirm(self):
        self._confirm_event.set()

    def stop(self):
        self._stop_event.set()
        self._confirm_event.set()

    def _wait_for_confirm(self, mensagem):
        self.waiting_callback(mensagem)
        while not self._stop_event.is_set():
            if self._confirm_event.wait(timeout=0.2):
                self._confirm_event.clear()
                if self._stop_event.is_set():
                    return False
                return True
        return False

    def _run(self):
        browser = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, channel="chrome")
                ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
                if STORAGE_STATE.is_file():
                    ctx_opts["storage_state"] = str(STORAGE_STATE)

                context = browser.new_context(**ctx_opts)
                page = context.new_page()

                self.log_callback(f"Acessando: {INSTAGRAM_URL}")
                page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
                time.sleep(4)

                precisa_logar = False
                if "/accounts/login" in page.url or "login" in page.url:
                    precisa_logar = True
                else:
                    try:
                        page.locator('input[name="username"], input[name="password"]').first.wait_for(
                            state="visible", timeout=2200
                        )
                        precisa_logar = True
                    except PlaywrightTimeoutError:
                        pass

                if precisa_logar:
                    self.log_callback("Instagram pediu login. Faca login no Chrome.")
                    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
                    if not self._wait_for_confirm(
                        "Depois de logar, abrir um post e visualizar o contador de curtidas, clique em 'Confirmar'."
                    ):
                        return
                    time.sleep(2)

                context.storage_state(path=str(STORAGE_STATE))
                self.log_callback(
                    "Modo inicial ativo. Abra o post desejado e clique em Confirmar para eu tentar abrir as curtidas."
                )

                while not self._stop_event.is_set():
                    if not self._wait_for_confirm("Post pronto? Clique em Confirmar para clicar em curtidas."):
                        break
                    if self._stop_event.is_set():
                        break
                    clicar_curtidas(page, self.log_callback)

                self.log_callback("Finalizando automacao e encerrando navegador...")
                browser.close()
                browser = None

        except Exception as exc:
            self.log_callback(f"Erro inesperado: {exc}")
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            self.finished_callback()

