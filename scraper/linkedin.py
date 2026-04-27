import threading
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

URL = "https://www.linkedin.com/feed/"
EXCEL_FILE = "ranking_engajamento.xlsx"
CSV_FILE = "ranking_engajamento.csv"
STORAGE_STATE = Path("linkedin_state.json")


def obter_url_post_ativo(page):
    urn = page.evaluate("""() => {
        let posts = document.querySelectorAll("div[data-urn*='activity']:not([data-urn*='activity'] [data-urn*='activity'])");
        let targetUrn = null;
        let maxVisibleArea = 0;

        for (let p of posts) {
            let rect = p.getBoundingClientRect();
            let visibleHeight = Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0);
            if (visibleHeight > maxVisibleArea) {
                maxVisibleArea = visibleHeight;
                targetUrn = p.getAttribute("data-urn");
            }
        }
        return targetUrn;
    }""")

    if urn:
        return f"https://www.linkedin.com/feed/update/{urn}/"
    return "URL nao identificada"


def extrair_reacoes(page, ranking_engajamento, post_url, log_callback):
    base_modal_selector = "div[role='dialog'].social-details-reactors-modal"
    modal = page.locator(base_modal_selector).first

    if not modal.is_visible():
        log_callback("ERRO: A janela de reacoes nao esta aberta.")
        return False

    log_callback(f"Link identificado: {post_url}")
    log_callback("Janela detectada. Rolando para carregar todas as reacoes...")

    seletor_scroll = f"{base_modal_selector} .artdeco-modal__content"
    seletor_nomes = f"{base_modal_selector} .artdeco-entity-lockup__title, {base_modal_selector} .artdeco-entity-title"

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0

    while tentativas_sem_novo_nome < 3:
        quantidade_atual = page.locator(seletor_nomes).count()
        if quantidade_atual == pessoas_carregadas:
            tentativas_sem_novo_nome += 1
        else:
            tentativas_sem_novo_nome = 0
            pessoas_carregadas = quantidade_atual

        page.evaluate(
            f"""
            var objDiv = document.querySelector("{seletor_scroll}");
            if(objDiv) {{ objDiv.scrollTop = objDiv.scrollHeight; }}
        """
        )
        time.sleep(1.5)

    elementos_nome = page.locator(seletor_nomes).all_inner_texts()
    novas_reacoes = 0

    for texto in elementos_nome:
        nome_limpo = texto.split("\n")[0].strip()
        if nome_limpo:
            ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0, "urls": set()})
            ranking_engajamento[nome_limpo]["reacoes"] += 1
            ranking_engajamento[nome_limpo]["urls"].add(post_url)
            novas_reacoes += 1

    log_callback(f"{novas_reacoes} reacoes mapeadas neste post.")
    log_callback("Abra a proxima janela de reacoes e clique em Confirmar para continuar.")
    page.keyboard.press("Escape")
    time.sleep(1)
    return True


def salvar_relatorio(ranking_engajamento, log_callback):
    dados_finais = []
    for nome, dados in ranking_engajamento.items():
        total_engajamento = dados["reacoes"] + dados["comentarios"]
        urls_formatadas = ", ".join(dados["urls"])
        dados_finais.append(
            {
                "nome": nome,
                "Qtd_Reacoes": dados["reacoes"],
                "Qtd_Comentarios": dados["comentarios"],
                "Engajamento_Total": total_engajamento,
                "URLs_dos_Posts": urls_formatadas,
            }
        )

    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Engajamento_Total", ascending=False)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        log_callback(f"SUCESSO: {len(dados_finais)} pessoas no ranking.")
        log_callback(f"Arquivos gerados: {CSV_FILE} e {EXCEL_FILE}")
    else:
        log_callback("Nenhum dado de engajamento foi coletado.")


class LinkedInRunner:
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
        ranking_engajamento = {}
        browser = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, channel="chrome")
                ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
                if STORAGE_STATE.is_file():
                    ctx_opts["storage_state"] = str(STORAGE_STATE)

                context = browser.new_context(**ctx_opts)
                page = context.new_page()

                self.log_callback(f"Acessando: {URL}")
                page.goto(URL, wait_until="domcontentloaded")
                time.sleep(4)

                precisa_logar = False
                if "signup" in page.url or "authwall" in page.url or "login" in page.url:
                    precisa_logar = True
                elif page.locator(
                    'a[href*="/login"], button:has-text("Entrar"), button:has-text("Sign in")'
                ).first.is_visible(timeout=3000):
                    precisa_logar = True

                if precisa_logar:
                    self.log_callback("LinkedIn pediu login. Faca login no Chrome.")
                    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
                    if not self._wait_for_confirm("Depois de logar e abrir o feed, clique em 'Confirmar'."):
                        return
                    time.sleep(3)
                    page.goto(URL, wait_until="domcontentloaded")
                    time.sleep(3)

                context.storage_state(path=str(STORAGE_STATE))
                contador_posts = 0
                self.log_callback("Coleta iniciada. Abra reacoes no Chrome e clique em Confirmar.")

                while not self._stop_event.is_set():
                    prompt = f"[Post {contador_posts + 1}] Janela de reacoes aberta? Clique em Confirmar."
                    if not self._wait_for_confirm(prompt):
                        break
                    if self._stop_event.is_set():
                        break

                    post_url = obter_url_post_ativo(page)
                    sucesso_reacoes = extrair_reacoes(page, ranking_engajamento, post_url, self.log_callback)
                    if sucesso_reacoes:
                        contador_posts += 1

                self.log_callback("Finalizando coleta e encerrando navegador...")
                browser.close()
                browser = None

            salvar_relatorio(ranking_engajamento, self.log_callback)
        except Exception as exc:
            self.log_callback(f"Erro inesperado: {exc}")
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            self.finished_callback()
