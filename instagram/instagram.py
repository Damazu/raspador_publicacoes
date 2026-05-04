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
    import time
    
    try:
        page.wait_for_selector('div[role="dialog"]:visible', timeout=4000)
    except:
        log_callback("ERRO: A janela de curtidas nao foi detectada na tela.")
        return False

    post_url = page.url 
    log_callback(f"Capturando Usuários e Nomes Reais do link: {post_url}")

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0
    # Agora usamos um dicionário local para guardar { "usuario": "Nome Real" }
    usuarios_coletados_neste_post = {}

    while tentativas_sem_novo_nome < 12:
        
        # A MÁGICA DE VÍNCULO NO JAVASCRIPT:
        # Ele captura o @usuario e "sobe" no HTML para encontrar o Nome Real da mesma linha
        dados_js = page.evaluate('''() => {
            const modals = document.querySelectorAll('div[role="dialog"]');
            const visibleModal = Array.from(modals).reverse().find(m => m.offsetHeight > 0);
            if (!visibleModal) return [];

            const results = [];
            const userSpans = visibleModal.querySelectorAll('a[role="link"] span[dir="auto"]');

            userSpans.forEach(span => {
                const username = span.innerText.trim();
                if (!username) return;

                let realName = "";
                let currentElement = span.closest('a');

                // Sobe até 6 níveis na árvore HTML da pessoa para procurar o span solto do Nome Real
                for (let i = 0; i < 6; i++) {
                    if (!currentElement || !currentElement.parentElement) break;
                    currentElement = currentElement.parentElement;

                    const possibleRealNameSpan = Array.from(currentElement.querySelectorAll('span[dir="auto"]'))
                        .find(s => !s.closest('a') && s.innerText.trim().length > 0);

                    if (possibleRealNameSpan) {
                        realName = possibleRealNameSpan.innerText.trim();
                        break;
                    }
                }
                results.push({ username: username, realName: realName });
            });

            return results;
        }''')
        
        for item in dados_js:
            user = item["username"]
            real = item["realName"]
            
            if user and "\n" not in user and len(user) < 35:
                if user.lower() not in ["seguir", "seguindo", "remover", "solicitado"]:
                    usuarios_coletados_neste_post[user] = real

        quantidade_atual = len(usuarios_coletados_neste_post)
        
        if quantidade_atual == pessoas_carregadas:
            tentativas_sem_novo_nome += 1
            if tentativas_sem_novo_nome > 6:
                log_callback(f"Aguardando carregamento da lista... ({tentativas_sem_novo_nome}/10)")
        else:
            tentativas_sem_novo_nome = 0
            pessoas_carregadas = quantidade_atual
            log_callback(f"Pares (Usuário+Nome) encontrados até agora: {pessoas_carregadas}")
            
            page.evaluate('''
                const modals = document.querySelectorAll('div[role="dialog"]');
                const visibleModal = Array.from(modals).reverse().find(m => m.offsetHeight > 0);
                if (visibleModal) {
                    const scrollableDiv = Array.from(visibleModal.querySelectorAll('div')).find(
                        el => getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll'
                    );
                    if (scrollableDiv) scrollableDiv.scrollBy(0, 400);
                }
            ''')
        
        time.sleep(1.2) 

    # Consolida os dados no ranking
    novas_curtidas = 0
    for usuario, nome_real in usuarios_coletados_neste_post.items():
        ranking_engajamento.setdefault(usuario, {"nome_real": "", "curtidas": 0, "comentarios": 0, "urls": set()})
        
        # Só atualiza o Nome Real se achou um (para não apagar se ele já existir)
        if nome_real:
            ranking_engajamento[usuario]["nome_real"] = nome_real
            
        ranking_engajamento[usuario]["curtidas"] += 1
        ranking_engajamento[usuario]["urls"].add(post_url)
        novas_curtidas += 1

    log_callback(f"SUCESSO: {novas_curtidas} contas mapeadas neste post.")
    log_callback("Agora vamos para o mapeamento dos comentários...")
    return True

def extrair_comentarios(page, ranking_engajamento, log_callback):
    import time
    
    try:
        page.wait_for_selector('article', timeout=4000)
    except:
        log_callback("ERRO: O post não foi detectado na tela.")
        return False

    post_url = page.url 
    log_callback(f"Capturando COMENTÁRIOS do link: {post_url}")

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0
    usuarios_coletados_neste_post = set()

    while tentativas_sem_novo_nome < 10:
        elementos = page.locator('article').last.locator('ul li h2 a, ul li h3 a').all_inner_texts()
        
        for user in elementos:
            nome_limpo = user.strip()
            if nome_limpo and "\n" not in nome_limpo and len(nome_limpo) < 35:
                usuarios_coletados_neste_post.add(nome_limpo)

        quantidade_atual = len(usuarios_coletados_neste_post)
        
        if quantidade_atual == pessoas_carregadas:
            tentativas_sem_novo_nome += 1
        else:
            tentativas_sem_novo_nome = 0
            pessoas_carregadas = quantidade_atual
            log_callback(f"Comentaristas encontrados até agora: {pessoas_carregadas}")
            
            page.evaluate('''
                const articles = document.querySelectorAll('article');
                const visibleArticle = Array.from(articles).reverse().find(a => a.offsetHeight > 0);
                if (visibleArticle) {
                    const scrollableDiv = Array.from(visibleArticle.querySelectorAll('*')).find(
                        el => (getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll') && el.offsetHeight > 100
                    );
                    if (scrollableDiv) scrollableDiv.scrollBy(0, 400);
                    else window.scrollBy(0, 400); 
                }
            ''')
        
        time.sleep(1.2) 

    novas_interacoes = 0
    for usuario in usuarios_coletados_neste_post:
        # Se a pessoa comentou mas não curtiu, ela é criada aqui com o Nome Real vazio
        ranking_engajamento.setdefault(usuario, {"nome_real": "", "curtidas": 0, "comentarios": 0, "urls": set()})
        ranking_engajamento[usuario]["comentarios"] += 1
        ranking_engajamento[usuario]["urls"].add(post_url)
        novas_interacoes += 1

    log_callback(f"SUCESSO: {novas_interacoes} comentaristas únicos mapeados neste post.")
    return True

def salvar_relatorio(ranking_engajamento, log_callback):
    import pandas as pd
    
    dados_finais = []
    for usuario, dados in ranking_engajamento.items():
        urls_formatadas = ", ".join(dados["urls"])
        
        dados_finais.append(
            {
                "Usuario_Instagram": usuario,
                "Nome_Real": dados["nome_real"],
                "Qtd_Curtidas": dados["curtidas"],
                "Qtd_Comentarios": dados["comentarios"],
                "Engajamento_Total": dados["curtidas"] + dados["comentarios"],
                "URLs_dos_Posts": urls_formatadas,
            }
        )

    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Engajamento_Total", ascending=False)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        log_callback(f"SUCESSO: {len(dados_finais)} contas unicas coletadas.")
        log_callback(f"Arquivos gerados: {CSV_FILE} e {EXCEL_FILE}")
    else:
        log_callback("Nenhum dado de engajamento foi coletado.")

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
                # Usamos domcontentloaded para evitar o erro de timeout do Instagram
                page.goto(INSTAGRAM_URL, wait_until="domcontentloaded")
                time.sleep(4)

                # --- Verificação de Login ---
                try:
                    page.wait_for_selector('svg[aria-label="Página inicial"], svg[aria-label="Direct"]', timeout=5000)
                    self.log_callback("Sessão ativa detectada.")
                except:
                    self.log_callback("Login necessário. Por favor, logue no Chrome.")
                    if not self._wait_for_confirm("Após logar e chegar na Home, clique em 'Confirmar'."):
                        return
                    context.storage_state(path=str(STORAGE_STATE))

                contador_posts = 0
                self.log_callback("Iniciando coleta em duas etapas (Curtidas e depois Comentários).")

                # --- LOOP PRINCIPAL POR POST ---
                while not self._stop_event.is_set():
                    indice_post = contador_posts + 1
                    
                    # ETAPA 1: CURTIDAS
                    prompt_curtidas = f"[Post {indice_post} - ETAPA 1/2] Abra o modal de CURTIDAS e clique em Confirmar."
                    if not self._wait_for_confirm(prompt_curtidas):
                        break
                    if self._stop_event.is_set():
                        break
                    
                    self.log_callback(f"Processando curtidas do Post {indice_post}...")
                    sucesso_curtidas = extrair_curtidas(page, ranking_engajamento, self.log_callback)
                    
                    if self._stop_event.is_set():
                        break

                    # ETAPA 2: COMENTÁRIOS
                    # Note: extrair_curtidas já aperta 'Escape' ao final, então o modal fecha sozinho.
                    prompt_comentarios = f"[Post {indice_post} - ETAPA 2/2] Modal de curtidas fechado. Agora role os COMENTÁRIOS e clique em Confirmar."
                    if not self._wait_for_confirm(prompt_comentarios):
                        break
                    if self._stop_event.is_set():
                        break
                    
                    self.log_callback(f"Processando comentários do Post {indice_post}...")
                    sucesso_comentarios = extrair_comentarios(page, ranking_engajamento, self.log_callback)

                    # Finalização do Post atual
                    if sucesso_curtidas or sucesso_comentarios:
                        contador_posts += 1
                        self.log_callback(f"✅ Post {contador_posts} finalizado com sucesso!")
                        self.log_callback("Pule para o próximo post no Instagram e aguarde o próximo prompt.")

                self.log_callback("Encerrando navegador e salvando dados...")
                if browser:
                    browser.close()
                browser = None

            # Gera o Excel/CSV final
            salvar_relatorio(ranking_engajamento, self.log_callback)

        except Exception as exc:
            self.log_callback(f"Erro inesperado no motor: {exc}")
        finally:
            if browser:
                browser.close()
            self.finished_callback()