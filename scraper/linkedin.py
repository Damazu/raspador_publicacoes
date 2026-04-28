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
        log_callback(f"Iniciando raspagem de comentários estrutural...")

        usuarios_coletados_neste_post = set()
        pessoas_carregadas = 0
        tentativas_sem_novo_nome = 0

        # Rola a tela um pouco para o centro para ativar o carregamento do LinkedIn
        safe_page_evaluate(page, "window.scrollBy(0, 300);")
        time.sleep(1.5)

        # Loop de "Pesca"
        while tentativas_sem_novo_nome < 4:
            
            # O Extrator JavaScript agora usa as "Minas de Ouro" do seu HTML
            nomes_brutos = safe_page_evaluate(page, """() => {
                let dados = new Set();

                // ESTRATÉGIA 1: O Botão de Opções do Comentário (100% preciso)
                let botoes = document.querySelectorAll('button[aria-label*="comentário de"], button[aria-label*="resposta de"]');
                botoes.forEach(btn => {
                    let label = btn.getAttribute('aria-label');
                    if (label) {
                        // Extrai tudo que está entre "comentário de " e o ponto final "."
                        let match = label.match(/(?:comentário de|resposta de) (.*?)(?:\.|$)/i);
                        if (match && match[1]) {
                            dados.add(match[1].trim());
                        }
                    }
                });

                // ESTRATÉGIA 2: A tag Span invisível (Fallback perfeito baseado no seu HTML)
                let spans = document.querySelectorAll('a[href*="/in/"] span[aria-hidden="true"], a[href*="/company/"] span[aria-hidden="true"]');
                spans.forEach(span => {
                    // Garante que pegamos apenas o nó de texto (nodeType 3), ignorando "Premium Perfil 2º"
                    if (span.childNodes.length > 0 && span.childNodes[0].nodeType === 3) { 
                        let nome = span.childNodes[0].nodeValue.trim();
                        if (nome.length > 2) {
                            dados.add(nome);
                        }
                    }
                });

                return Array.from(dados);
            }""")

            # Limpeza final no Python
            if nomes_brutos:
                for nome in nomes_brutos:
                    nome_limpo = nome.strip()
                    if not nome_limpo: continue

                    # Filtro de segurança caso o LinkedIn jogue lixo
                    lixo = ["link do gráfico", "gostei", "responder", "reações"]
                    if any(palavra in nome_limpo.lower() for palavra in lixo):
                        continue

                    usuarios_coletados_neste_post.add(nome_limpo)

            # Verifica progresso da contagem
            quantidade_atual = len(usuarios_coletados_neste_post)
            if quantidade_atual == pessoas_carregadas:
                tentativas_sem_novo_nome += 1
            else:
                tentativas_sem_novo_nome = 0
                pessoas_carregadas = quantidade_atual
                log_callback(f"Comentários detectados até agora: {pessoas_carregadas}")

            # Scroll para expor novos comentários
            safe_page_evaluate(page, """() => {
                let modal = document.querySelector('div[role="dialog"]');
                if (modal) {
                    let scrollable = Array.from(modal.querySelectorAll('div')).find(
                        el => getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll'
                    );
                    if (scrollable) { scrollable.scrollBy(0, 600); } 
                    else { modal.scrollBy(0, 600); }
                } else {
                    window.scrollBy(0, 600);
                }
            }""")
            
            time.sleep(1.5)

        # Adiciona os dados coletados no dicionário mestre
        novos_comentarios = 0
        for nome_limpo in usuarios_coletados_neste_post:
            
            # ATENÇÃO: Se não quiser que a própria empresa contabilize comentários, remova o "#" da linha abaixo e mude "houer" pelo nome que aparece nela
            # if nome_limpo.lower() == "houer": continue 
            
            ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0, "urls": set()})
            ranking_engajamento[nome_limpo]["comentarios"] += 1
            ranking_engajamento[nome_limpo]["urls"].add(post_url)
            novos_comentarios += 1

        log_callback(f"SUCESSO: {novos_comentarios} comentários únicos mapeados neste post.")
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
