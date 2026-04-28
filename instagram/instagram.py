import threading
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

INSTAGRAM_URL = "https://www.instagram.com/"
EXCEL_FILE = "ranking_engajamento_instagram.xlsx"
CSV_FILE = "ranking_engajamento_instagram.csv"
STORAGE_STATE = Path("instagram_state.json")

def extrair_curtidas(page, ranking_engajamento, log_callback):
    # CORREÇÃO 1: Adicionamos ':visible' para ignorar qualquer modal fantasma/oculto no HTML
    try:
        page.wait_for_selector('div[role="dialog"]:visible', timeout=3000)
    except:
        log_callback("ERRO: A janela de curtidas nao foi detectada na tela.")
        return False

    post_url = page.url 
    log_callback(f"Capturando curtidas do link: {post_url}")
    log_callback("Modal detectado. Rolando para carregar todas as curtidas...")

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0
    usuarios_coletados_neste_post = set()

    # Loop de scroll
    while tentativas_sem_novo_nome < 4:
        # CORREÇÃO 2: Busca os textos apenas dentro do modal que está efetivamente visível
        elementos = page.locator('div[role="dialog"]:visible span[dir="auto"]').all_inner_texts()
        
        for user in elementos:
            nome_limpo = user.strip()
            # Filtra textos genéricos vazios ou textos grandes que não são arrobas
            if nome_limpo and "\n" not in nome_limpo and len(nome_limpo) < 35:
                usuarios_coletados_neste_post.add(nome_limpo)

        quantidade_atual = len(usuarios_coletados_neste_post)
        if quantidade_atual == pessoas_carregadas:
            tentativas_sem_novo_nome += 1
        else:
            tentativas_sem_novo_nome = 0
            pessoas_carregadas = quantidade_atual
            log_callback(f"Usuários encontrados até agora: {pessoas_carregadas}")

        # CORREÇÃO 3: O JavaScript agora encontra o modal visível na tela (offsetHeight > 0)
        page.evaluate('''
            const modals = document.querySelectorAll('div[role="dialog"]');
            const visibleModal = Array.from(modals).find(m => m.offsetHeight > 0);
            
            if (visibleModal) {
                const scrollableDiv = Array.from(visibleModal.querySelectorAll('div')).find(
                    el => getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll'
                );
                if (scrollableDiv) {
                    scrollableDiv.scrollTop = scrollableDiv.scrollHeight;
                }
            }
        ''')
        time.sleep(1.5) # Tempo para o Instagram carregar a listagem (aumente se sua internet oscilar)

    # Consolida os dados no ranking geral
    novas_curtidas = 0
    for nome_limpo in usuarios_coletados_neste_post:
        ranking_engajamento.setdefault(nome_limpo, {"curtidas": 0, "urls": set()})
        ranking_engajamento[nome_limpo]["curtidas"] += 1
        ranking_engajamento[nome_limpo]["urls"].add(post_url)
        novas_curtidas += 1

    log_callback(f"{novas_curtidas} curtidas mapeadas neste post.")
    log_callback("Abra a proxima janela de curtidas (em outro post) e clique em Confirmar.")
    
    # Tenta fechar o modal apertando Esc para facilitar sua vida na navegação
    page.keyboard.press("Escape")
    time.sleep(1)
    return True

def salvar_relatorio(ranking_engajamento, log_callback):
    dados_finais = []
    for nome, dados in ranking_engajamento.items():
        urls_formatadas = ", ".join(dados["urls"])
        dados_finais.append(
            {
                "Nome_Usuario": nome,
                "Qtd_Curtidas": dados["curtidas"],
                "URLs_dos_Posts": urls_formatadas,
            }
        )

    if dados_finais:
        df = pd.DataFrame(dados_finais)
        # Ordena para quem curtiu mais vezes ficar no topo
        df = df.sort_values(by="Qtd_Curtidas", ascending=False)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        log_callback(f"SUCESSO: {len(dados_finais)} contas unicas coletadas.")
        log_callback(f"Arquivos gerados: {CSV_FILE} e {EXCEL_FILE}")
    else:
        log_callback("Nenhum dado de engajamento foi coletado ou não rolou o STOP.")


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

                self.log_callback(f"Acessando: {INSTAGRAM_URL}")
                page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
                time.sleep(4)

                # Verifica Login
                precisa_logar = False
                if "/accounts/login" in page.url or "login" in page.url:
                    precisa_logar = True
                else:
                    try:
                        page.locator('input[name="username"]').first.wait_for(state="visible", timeout=3000)
                        precisa_logar = True
                    except:
                        pass

                if precisa_logar:
                    self.log_callback("Instagram pediu login. Faca login no Chrome.")
                    page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
                    if not self._wait_for_confirm("Depois de logar, clique em 'Confirmar'."):
                        return
                    time.sleep(3)

                context.storage_state(path=str(STORAGE_STATE))
                contador_posts = 0
                self.log_callback("Coleta iniciada. Navegue até o post, ABRA as curtidas e clique em Confirmar.")

                # Loop de posts
                while not self._stop_event.is_set():
                    prompt = f"[Post {contador_posts + 1}] Modal de curtidas ABERTO? Clique em Confirmar."
                    if not self._wait_for_confirm(prompt):
                        break
                    if self._stop_event.is_set():
                        break

                    sucesso_curtidas = extrair_curtidas(page, ranking_engajamento, self.log_callback)
                    if sucesso_curtidas:
                        contador_posts += 1

                self.log_callback("Finalizando coleta e encerrando navegador...")
                browser.close()
                browser = None

            # O salvamento do relatório roda após o fechamento do browser (seja clicando em Stop ou finalizando)
            salvar_relatorio(ranking_engajamento, self.log_callback)

        except Exception as exc:
            self.log_callback(f"Erro inesperado: {exc}")
        finally:
            if browser is not None:
                try:
                    browser.close()
                except:
                    pass
            self.finished_callback()