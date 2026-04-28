import threading
import time
from pathlib import Path

import pandas as pd
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URL = "https://www.linkedin.com/company/houer/posts/?feedView=all&sortBy=RECENT"
EXCEL_FILE = "ranking_engajamento.xlsx"
CSV_FILE = "ranking_engajamento.csv"
STORAGE_STATE = Path("linkedin_state.json")


def safe_page_evaluate(page, script, retries=2, wait_seconds=1.2):
    for tentativa in range(retries + 1):
        try:
            return page.evaluate(script)
        except PlaywrightError as exc:
            mensagem = str(exc).lower()
            if "execution context was destroyed" in mensagem or "most likely because of a navigation" in mensagem:
                if tentativa >= retries:
                    raise
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass
                time.sleep(wait_seconds)
                continue
            raise


def obter_url_post_ativo(page):
    urn = safe_page_evaluate(page, """() => {
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

        safe_page_evaluate(
            page,
            f"""
            var objDiv = document.querySelector("{seletor_scroll}");
            if(objDiv) {{ objDiv.scrollTop = objDiv.scrollHeight; }}
        """,
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

def extrair_comentarios(page, ranking_engajamento, post_url, log_callback):
    try:
        log_callback(f"Iniciando raspagem de comentários. Lendo a tela...")

        # Seletores mais abrangentes que pegam o nome do autor do comentário e de respostas (replies)
        seletor_nomes = ".comments-post-meta__name-text, span.comments-post-meta__name div[dir='ltr']"
        
        usuarios_coletados_neste_post = set()
        pessoas_carregadas = 0
        tentativas_sem_novo_nome = 0

        # Dá um pequeno scroll para cima para garantir que não perdemos o primeiro comentário
        safe_page_evaluate(page, "window.scrollBy(0, -500);")
        time.sleep(1)

        # Loop de "Pesca": Rola a tela para baixo aos poucos para forçar o LinkedIn 
        # a colocar os próximos comentários no código HTML (Virtual DOM).
        while tentativas_sem_novo_nome < 4:
            
            # 1. Pega os nomes que estão renderizados na tela neste exato segundo
            try:
                elementos_nome = page.locator(seletor_nomes).all_inner_texts()
                
                for texto in elementos_nome:
                    # Limpa quebras de linha e o "• 1º grau" que o LinkedIn costuma grudar no nome
                    nome_limpo = texto.split("\n")[0].split("•")[0].strip()
                    
                    # Filtra nomes vazios ou usuários anônimos
                    if nome_limpo and "LinkedIn Member" not in nome_limpo and "Usuário do LinkedIn" not in nome_limpo:
                        usuarios_coletados_neste_post.add(nome_limpo)
            except Exception:
                pass

            # 2. Verifica se a quantidade de pessoas únicas na nossa "rede" aumentou
            quantidade_atual = len(usuarios_coletados_neste_post)
            if quantidade_atual == pessoas_carregadas:
                tentativas_sem_novo_nome += 1
            else:
                tentativas_sem_novo_nome = 0
                pessoas_carregadas = quantidade_atual
                log_callback(f"Comentários contabilizados até agora: {pessoas_carregadas}")

            # 3. Rola a página para baixo para expor o próximo lote de comentários
            # O mouse.wheel é excelente porque rola a página independentemente de ser um modal ou o feed principal
            try:
                page.mouse.wheel(0, 700)
            except Exception:
                safe_page_evaluate(page, "window.scrollBy(0, 700);")
                
            time.sleep(1.5) # Tempo crucial para o LinkedIn processar o scroll e injetar o HTML

        # Consolidação: Agora que temos todos os nomes únicos, jogamos no dicionário principal
        novos_comentarios = 0
        for nome_limpo in usuarios_coletados_neste_post:
            ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0, "urls": set()})
            
            # Adiciona +1 apenas na coluna de comentários deste usuário
            ranking_engajamento[nome_limpo]["comentarios"] += 1
            ranking_engajamento[nome_limpo]["urls"].add(post_url)
            novos_comentarios += 1

        log_callback(f"SUCESSO: {novos_comentarios} comentários mapeados neste post.")
        return True

    except Exception as e:
        log_callback(f"Erro ao extrair comentários: {e}")
        return False

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

def sessao_linkedin_ativa(page):
    indicadores_logado = [
        'button[aria-label*="Eu"]',
        'a[href="/feed/"]',
        'a[href*="/mynetwork/"]',
        'input[placeholder*="Pesquisar"]',
        'input[aria-label*="Pesquisar"]',
    ]

    for seletor in indicadores_logado:
        try:
            if page.locator(seletor).first.is_visible(timeout=1200):
                return True
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    return False


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

                self.log_callback("Acessando o LinkedIn...")
                
                # CORREÇÃO 1: Trata o erro de interrupção de rota do LinkedIn
                try:
                    page.goto(URL, wait_until="domcontentloaded")
                except Exception as e:
                    if "interrupted" in str(e).lower():
                        self.log_callback("Redirecionamento automático detectado. Aguardando estabilizar...")
                        time.sleep(3)
                    else:
                        raise e

                time.sleep(3)

                # Verifica se precisa logar
                precisa_logar = False
                if "signup" in page.url or "authwall" in page.url or "login" in page.url:
                    precisa_logar = True
                elif not sessao_linkedin_ativa(page):
                    precisa_logar = True

                if precisa_logar:
                    self.log_callback("LinkedIn pediu login. Faca login no Chrome.")
                    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
                    if not self._wait_for_confirm("Depois de logar e o feed carregar, clique em 'Confirmar'."):
                        return
                    time.sleep(3)

                    if not sessao_linkedin_ativa(page):
                        self.log_callback("ERRO: Login ainda nao detectado. Conecte a conta e clique em Confirmar novamente.")
                        if not self._wait_for_confirm("Finalize o login no LinkedIn e clique em 'Confirmar'."):
                            return
                        time.sleep(2)
                        if not sessao_linkedin_ativa(page):
                            self.log_callback("ERRO: Nao foi possivel confirmar sessao logada no LinkedIn.")
                            return
                    
                context.storage_state(path=str(STORAGE_STATE))

                # CORREÇÃO 2: Força a ida para a URL alvo APÓS o login estar confirmado
                if "company/houer" not in page.url:
                    self.log_callback("Indo para a página alvo dos posts...")
                    page.goto(URL, wait_until="domcontentloaded")
                    time.sleep(4)

                contador_posts = 0
                self.log_callback("Coleta iniciada em etapas: 1) Reacoes, 2) Comentarios.")

                while not self._stop_event.is_set():
                    indice_post = contador_posts + 1
                    prompt_reacoes = (
                        f"[Post {indice_post} - Etapa 1/2] Abra a janela de reacoes e clique em Confirmar."
                    )
                    if not self._wait_for_confirm(prompt_reacoes):
                        break
                    if self._stop_event.is_set():
                        break

                    post_url = obter_url_post_ativo(page)
                    sucesso_reacoes = extrair_reacoes(page, ranking_engajamento, post_url, self.log_callback)

                    prompt_comentarios = (
                        f"[Post {indice_post} - Etapa 2/2] Abra os comentarios do mesmo post e clique em Confirmar."
                    )
                    if not self._wait_for_confirm(prompt_comentarios):
                        break
                    if self._stop_event.is_set():
                        break

                    sucesso_comentarios = extrair_comentarios(page, ranking_engajamento, post_url, self.log_callback)
                    
                    if sucesso_reacoes or sucesso_comentarios:
                        contador_posts += 1
                        self.log_callback(f"--- Post {contador_posts} finalizado (reacoes + comentarios). Role para o proximo. ---")

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
