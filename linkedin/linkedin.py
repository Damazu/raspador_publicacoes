import threading
import time
from pathlib import Path

import pandas as pd
from paths_utils import pasta_area_trabalho
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URL = "https://www.linkedin.com/feed/"
EXCEL_FILE = "ranking_engajamento_linkedin.xlsx"
CSV_FILE = "ranking_engajamento_linkedin.csv"
STORAGE_STATE = Path("linkedin_state.json")


def garantir_pessoa(ranking_engajamento_linkedin, nome):
    ranking_engajamento_linkedin.setdefault(
        nome,
        {
            "reacoes": 0,
            "comentarios": 0,
            "compartilhamentos_com_pensamentos": 0,
            "compartilhamentos_sem_pensamentos": 0,
            "urls": set(),
        },
    )

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

def extrair_reacoes(page, ranking_engajamento_linkedin, post_url, log_callback):
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
            garantir_pessoa(ranking_engajamento_linkedin, nome_limpo)
            ranking_engajamento_linkedin[nome_limpo]["reacoes"] += 1
            ranking_engajamento_linkedin[nome_limpo]["urls"].add(post_url)
            novas_reacoes += 1

    log_callback(f"{novas_reacoes} reacoes mapeadas neste post.")
    log_callback("Abra a proxima janela de reacoes e clique em Confirmar para continuar.")
    page.keyboard.press("Escape")
    time.sleep(1)
    return True

def extrair_compartilhamentos(page, ranking_engajamento_linkedin, post_url, log_callback):
    # 1. Atualizado para a classe específica do modal de compartilhamentos (Reposts)
    base_modal_selector = "div[role='dialog'].feed-modals-reposts-modal"
    
    try:
        log_callback("Aguardando a janela de compartilhamentos abrir...")
        # Usamos wait_for_selector para maior estabilidade, igual recomendado antes
        page.wait_for_selector(base_modal_selector, state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        log_callback("ERRO: A janela de compartilhamentos nao esta aberta.")
        return False

    log_callback(f"Link identificado: {post_url}")
    log_callback("Janela de compartilhamentos detectada. Rolando para carregar todos os posts...")

    # 2. Seletores de rolagem e dos cards (publicações compartilhadas)
    seletor_scroll = f"{base_modal_selector} .artdeco-modal__content"
    # Cada compartilhamento no LinkedIn é encapsulado nesta classe específica
    seletor_cards = f"{base_modal_selector} .feed-shared-update-v2"

    quantidade_anterior = 0
    tentativas_sem_novidade = 0

    # 3. Lógica de Infinite Scroll (Idêntica à de reações)
    while tentativas_sem_novidade < 3:
        quantidade_atual = page.locator(seletor_cards).count()
        if quantidade_atual == quantidade_anterior:
            tentativas_sem_novidade += 1
        else:
            tentativas_sem_novidade = 0
            quantidade_anterior = quantidade_atual

        # Rolagem via JavaScript focada no container interno do modal
        safe_page_evaluate(
            page,
            f"""
            var objDiv = document.querySelector("{seletor_scroll}");
            if(objDiv) {{ objDiv.scrollTop = objDiv.scrollHeight; }}
            """
        )
        time.sleep(1.5)

    # 4. Processamento dos Cards Carregados
    cards = page.locator(seletor_cards)
    total_cards = cards.count()
    vistos = set()
    com_pensamentos = 0
    sem_pensamentos = 0

    for i in range(total_cards):
        card = cards.nth(i)
        
        # Busca pelo indicador de "Sem ideia" (Repost simples, classe header padrão)
        header_sem_ideia = card.locator(".update-components-header__text-view")
        
        if header_sem_ideia.count() > 0:
            possui_pensamento = False
            nome_locator = header_sem_ideia.locator("a").first
            if nome_locator.count() > 0:
                nome_limpo = nome_locator.inner_text().strip()
            else:
                continue
                
        else:
            # Caso contrário, é "Com ideia" (Post com comentário / Quote)
            possui_pensamento = True
            # Pega o nome dentro do container de ator, evitando texto de acessibilidade duplicado
            nome_locator = card.locator(".update-components-actor__title span[dir='ltr'] span[aria-hidden='true']").first
            
            # Fallback de segurança 
            if nome_locator.count() == 0:
                nome_locator = card.locator(".update-components-actor__title .hoverable-link-text").first
                
            if nome_locator.count() > 0:
                nome_limpo = nome_locator.inner_text().strip()
            else:
                continue

        # Validação do nome encontrado
        if not nome_limpo or nome_limpo in vistos:
            continue

        # Registro no dicionário
        garantir_pessoa(ranking_engajamento_linkedin, nome_limpo)
        
        if possui_pensamento:
            ranking_engajamento_linkedin[nome_limpo]["compartilhamentos_com_pensamentos"] += 1
            com_pensamentos += 1
        else:
            ranking_engajamento_linkedin[nome_limpo]["compartilhamentos_sem_pensamentos"] += 1
            sem_pensamentos += 1

        ranking_engajamento_linkedin[nome_limpo]["urls"].add(post_url)
        vistos.add(nome_limpo)

    # 5. Finalização
    log_callback(
        f"Compartilhamentos mapeados: {com_pensamentos} com pensamentos e {sem_pensamentos} sem pensamentos."
    )
    log_callback("Abra a proxima janela de compartilhamentos e clique em Confirmar para continuar.")
    
    # Fecha o modal suavemente
    page.keyboard.press("Escape")
    time.sleep(1)
    
    return True

def extrair_comentarios(page, ranking_engajamento_linkedin, post_url, log_callback):
    try:
        log_callback(f"Iniciando raspagem de comentários estrutural...")

        # 1. Extrai o ID único (URN) do post a partir da URL
        import re
        match_urn = re.search(r'(urn:li:activity:\d+)', post_url)
        urn_alvo = match_urn.group(1) if match_urn else ""

        if not urn_alvo:
            log_callback("ERRO: Não foi possível identificar a identidade (URN) do post. Abortando extração.")
            return False

        usuarios_coletados_neste_post = set()
        pessoas_carregadas = 0
        tentativas_sem_novo_nome = 0

        # Rola a tela um pouco para o centro apenas no início
        safe_page_evaluate(page, "window.scrollBy(0, 200);")
        import time
        time.sleep(1.5)

        # Loop de "Pesca" - Reduzido para 3 tentativas para ser mais ágil
        while tentativas_sem_novo_nome < 3:
            
            nomes_brutos = safe_page_evaluate(page, rf"""() => {{
                let dados = new Set();
                
                // ISOLAMENTO PERFEITO: Procura APENAS dentro do post atual usando o URN
                let container = document.querySelector('div[data-urn="{urn_alvo}"]');
                if (!container) return [];

                // ESTRATÉGIA 1: O Botão de Opções do Comentário
                let botoes = container.querySelectorAll('button[aria-label*="comentário de"], button[aria-label*="resposta de"]');
                botoes.forEach(btn => {{
                    let label = btn.getAttribute('aria-label');
                    if (label) {{
                        let match = label.match(/(?:comentário de|resposta de) (.*?)(?:\.|$)/i);
                        if (match && match[1]) dados.add(match[1].trim());
                    }}
                }});

                // ESTRATÉGIA 2: A tag Span invisível
                let spans = container.querySelectorAll('a[href*="/in/"] span[aria-hidden="true"], a[href*="/company/"] span[aria-hidden="true"]');
                spans.forEach(span => {{
                    if (span.childNodes.length > 0 && span.childNodes[0].nodeType === 3) {{ 
                        let nome = span.childNodes[0].nodeValue.trim();
                        if (nome.length > 2) dados.add(nome);
                    }}
                }});

                return Array.from(dados);
            }}""")

            if nomes_brutos:
                for nome in nomes_brutos:
                    nome_limpo = nome.strip()
                    if not nome_limpo: continue

                    lixo = ["link do gráfico", "gostei", "responder", "reações"]
                    if any(palavra in nome_limpo.lower() for palavra in lixo):
                        continue

                    usuarios_coletados_neste_post.add(nome_limpo)

            # --- A MUDANÇA ESTÁ AQUI ---
            quantidade_atual = len(usuarios_coletados_neste_post)
            if quantidade_atual == pessoas_carregadas:
                # Não achou ninguém novo. Apenas soma a tentativa e FICA PARADO (sem scroll)
                tentativas_sem_novo_nome += 1
            else:
                # Achou comentários novos! Zera as tentativas e DÁ O SCROLL para tentar carregar mais
                tentativas_sem_novo_nome = 0
                pessoas_carregadas = quantidade_atual
                log_callback(f"Comentários detectados até agora: {pessoas_carregadas}")
                
                # Rola suavemente apenas se detectou avanço
                safe_page_evaluate(page, "window.scrollBy(0, 300);")

            time.sleep(1.5)

        # Adiciona os dados coletados no dicionário mestre
        novos_comentarios = 0
        for nome_limpo in usuarios_coletados_neste_post:
            
            # if nome_limpo.lower() == "empresa": continue 
            
            garantir_pessoa(ranking_engajamento_linkedin, nome_limpo)
            ranking_engajamento_linkedin[nome_limpo]["comentarios"] += 1
            ranking_engajamento_linkedin[nome_limpo]["urls"].add(post_url)
            novos_comentarios += 1

        log_callback(f"SUCESSO: {novos_comentarios} comentários únicos mapeados neste post.")
        return True

    except Exception as e:
        log_callback(f"Erro ao extrair comentários: {e}")
        return False

def salvar_relatorio(ranking_engajamento_linkedin, log_callback):
    dados_finais = []
    for nome, dados in ranking_engajamento_linkedin.items():
        total_engajamento = (
            dados["reacoes"]
            + dados["comentarios"]
            + dados["compartilhamentos_com_pensamentos"]
            + dados["compartilhamentos_sem_pensamentos"]
        )
        urls_formatadas = ", ".join(dados["urls"])
        dados_finais.append(
            {
                "nome": nome,
                "Qtd_Reacoes": dados["reacoes"],
                "Qtd_Comentarios": dados["comentarios"],
                "Qtd_Compartilhamentos_Com_Pensamentos": dados["compartilhamentos_com_pensamentos"],
                "Qtd_Compartilhamentos_Sem_Pensamentos": dados["compartilhamentos_sem_pensamentos"],
                "Engajamento_Total": total_engajamento,
                "URLs_dos_Posts": urls_formatadas,
            }
        )

    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Engajamento_Total", ascending=False)
        caminho_excel = pasta_area_trabalho() / EXCEL_FILE
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        df.to_excel(caminho_excel, index=False, engine="openpyxl")
        log_callback(f"SUCESSO: {len(dados_finais)} pessoas no ranking.")
        log_callback(f"Arquivos gerados: {CSV_FILE} (pasta do projeto) e {caminho_excel.resolve()} (Excel na area de trabalho)")
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
    def __init__(self, log_callback, waiting_callback, finished_callback, stage_callback=None):
        self.log_callback = log_callback
        self.waiting_callback = waiting_callback
        self.finished_callback = finished_callback
        self.stage_callback = stage_callback
        self._confirm_event = threading.Event()
        self._stop_event = threading.Event()
        self._skip_post_event = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._confirm_event.clear()
        self._stop_event.clear()
        self._skip_post_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def confirm(self):
        self._confirm_event.set()

    def stop(self):
        self._stop_event.set()
        self._confirm_event.set()

    def request_skip_current_post(self):
        self._skip_post_event.set()
        self._confirm_event.set()

    def _consume_skip_request(self):
        if self._skip_post_event.is_set():
            self._skip_post_event.clear()
            return True
        return False

    def _notify_stage(self, stage):
        if callable(self.stage_callback):
            try:
                self.stage_callback(stage)
            except Exception:
                pass

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
        ranking_engajamento_linkedin = {}
        browser = None

        try:
            self._notify_stage("idle")
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
                    self.log_callback("LinkedIn pediu login. Faca login no Chrome. Ao finalizar, clique em 'Confirmar'.")
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
                if "feed" not in page.url:
                    self.log_callback("Indo para a página alvo dos posts...")
                    page.goto(URL, wait_until="domcontentloaded")
                    time.sleep(4)

                contador_posts = 0
                self.log_callback(
                    "Coleta iniciada em etapas: 1) Reacoes, 2) Comentarios, 3) Compartilhamentos."
                )
                self._notify_stage("aguardando_etapa1")

                while not self._stop_event.is_set():
                    indice_post = contador_posts + 1
                    prompt_reacoes = (
                        f"[Post {indice_post} - Etapa 1/3] Abra a janela de reacoes e clique em Confirmar."
                    )
                    if not self._wait_for_confirm(prompt_reacoes):
                        break
                    if self._stop_event.is_set():
                        break

                    post_url = obter_url_post_ativo(page)
                    sucesso_reacoes = extrair_reacoes(page, ranking_engajamento_linkedin, post_url, self.log_callback)
                    self._notify_stage("etapa1_concluida")

                    if self._consume_skip_request():
                        if sucesso_reacoes:
                            contador_posts += 1
                        self.log_callback(
                            f"Post {indice_post} resetado apos etapa 1. Prosseguindo para validacao do proximo post."
                        )
                        self._notify_stage("aguardando_etapa1")
                        continue

                    prompt_comentarios = (
                        f"[Post {indice_post} - Etapa 2/3] Abra os comentarios do mesmo post e clique em Confirmar."
                    )
                    if not self._wait_for_confirm(prompt_comentarios):
                        break
                    if self._stop_event.is_set():
                        break
                    if self._consume_skip_request():
                        if sucesso_reacoes:
                            contador_posts += 1
                        self.log_callback(
                            f"Post {indice_post} resetado apos etapa 1. Prosseguindo para validacao do proximo post."
                        )
                        self._notify_stage("aguardando_etapa1")
                        continue

                    sucesso_comentarios = extrair_comentarios(page, ranking_engajamento_linkedin, post_url, self.log_callback)
                    if self._consume_skip_request():
                        if sucesso_reacoes or sucesso_comentarios:
                            contador_posts += 1
                        self.log_callback(
                            f"Post {indice_post} resetado apos etapa 1. Prosseguindo para validacao do proximo post."
                        )
                        self._notify_stage("aguardando_etapa1")
                        continue

                    prompt_compartilhamentos = (
                        f"[Post {indice_post} - Etapa 3/3] Abra a janela de compartilhamentos do mesmo post e clique em Confirmar."
                    )
                    if not self._wait_for_confirm(prompt_compartilhamentos):
                        break
                    if self._stop_event.is_set():
                        break
                    if self._consume_skip_request():
                        if sucesso_reacoes or sucesso_comentarios:
                            contador_posts += 1
                        self.log_callback(
                            f"Post {indice_post} resetado apos etapa 1. Prosseguindo para validacao do proximo post."
                        )
                        self._notify_stage("aguardando_etapa1")
                        continue

                    sucesso_compartilhamentos = extrair_compartilhamentos(
                        page, ranking_engajamento_linkedin, post_url, self.log_callback
                    )

                    if sucesso_reacoes or sucesso_comentarios or sucesso_compartilhamentos:
                        contador_posts += 1
                        self.log_callback(
                            f"--- Post {contador_posts} finalizado (reacoes + comentarios + compartilhamentos). ---"
                        )
                        
                        # === INÍCIO DA LIMPEZA INTELIGENTE (SEM RELOAD) ===
                        self.log_callback("Neutralizando HTML do post atual para evitar vazamentos...")
                        try:
                            safe_page_evaluate(page, """() => {
                                // 1. Neutraliza os botões de comentários já lidos
                                document.querySelectorAll('button[aria-label*="comentário de"], button[aria-label*="resposta de"]').forEach(btn => {
                                    btn.setAttribute('aria-label', 'processado-pelo-robo');
                                });

                                // 2. Neutraliza os spans invisíveis de nomes já lidos
                                document.querySelectorAll('span[aria-hidden="true"]').forEach(span => {
                                    span.setAttribute('aria-hidden', 'processado-pelo-robo');
                                });

                                // 3. Desativa modais fantasmas para não atrapalhar o scroll do próximo post
                                document.querySelectorAll('div[role="dialog"]').forEach(modal => {
                                    modal.setAttribute('role', 'dialog-processado');
                                    modal.style.display = 'none'; // Esconde de vez caso tenha ficado preso
                                });
                            }""")
                            self.log_callback("Memória limpa com sucesso! Posição mantida. Role para o PRÓXIMO post.")
                        except Exception as e:
                            self.log_callback(f"Aviso ao tentar limpar o HTML: {e}")
                        # === FIM DA LIMPEZA ===

                    self._notify_stage("aguardando_etapa1")

                self.log_callback("Finalizando coleta e encerrando navegador...")
                browser.close()
                browser = None

            salvar_relatorio(ranking_engajamento_linkedin, self.log_callback)
            
        except Exception as exc:
            self.log_callback(f"Erro inesperado: {exc}")
        finally:
            self._notify_stage("idle")
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            self.finished_callback()
