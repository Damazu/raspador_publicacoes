import json
import re
import threading
import time
from pathlib import Path

import pandas as pd
from paths_utils import caminho_estado_sessao, pasta_area_trabalho
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

INSTAGRAM_URL = "https://www.instagram.com/"
EXCEL_FILE = "ranking_engajamento_instagram.xlsx"
# JSON legado (ja nao e gravado): ainda lido se existir, para migrar sessoes antigas.
POSTS_JSON_FILE = "ranking_engajamento_instagram_por_post.json"
SHEET_RANKING = "Ranking"
SHEET_POR_POST = "PorPost"
# CSV_FILE = "ranking_engajamento_instagram.csv"
STORAGE_STATE = caminho_estado_sessao("instagram_state.json")

_RE_SHORTCODE_INSTAGRAM = re.compile(
    r"(?:instagram\.com/)(?:p|reels?|tv)/([A-Za-z0-9_-]+)", re.IGNORECASE
)

_SCRIPT_URL_POST_DOM = """() => {
    const patterns = [
        { re: /\\/p\\/([A-Za-z0-9_-]+)/, seg: 'p' },
        { re: /\\/reels?\\/([A-Za-z0-9_-]+)/, seg: 'reel' },
        { re: /\\/tv\\/([A-Za-z0-9_-]+)/, seg: 'tv' },
    ];
    function canonical(href) {
        if (!href) return '';
        let h = String(href).trim();
        if (h.startsWith('/')) h = 'https://www.instagram.com' + h;
        else if (!/^https?:/i.test(h)) h = 'https://www.instagram.com/' + h.replace(/^\\/+/, '');
        h = h.split('?')[0].split('#')[0];
        for (const { re, seg } of patterns) {
            const m = h.match(re);
            if (m) return `https://www.instagram.com/${seg}/${m[1]}/`;
        }
        return '';
    }
    function searchRoot(root) {
        if (!root) return '';
        let found = canonical(root.baseURI || location.href);
        if (found) return found;
        const links = root.querySelectorAll('a[href*="/p/"], a[href*="/reel"], a[href*="/tv/"]');
        for (const a of links) {
            found = canonical(a.getAttribute('href') || a.href);
            if (found) return found;
        }
        return '';
    }
    let url = canonical(location.href);
    if (url) return url;
    const modals = document.querySelectorAll('motiondialog, div[role="dialog"]');
    for (const m of Array.from(modals).reverse()) {
        if (m.offsetParent === null && m.offsetHeight === 0) continue;
        url = searchRoot(m);
        if (url) return url;
    }
    const articles = document.querySelectorAll('article');
    for (const a of Array.from(articles).reverse()) {
        url = searchRoot(a);
        if (url) return url;
    }
    return searchRoot(document.body);
}"""


def shortcode_post_instagram(url: str) -> str:
    if not url or (isinstance(url, float) and pd.isna(url)):
        return ""
    m = _RE_SHORTCODE_INSTAGRAM.search(str(url).strip())
    return m.group(1) if m else ""


def url_post_tem_shortcode(url: str) -> bool:
    return bool(shortcode_post_instagram(url))


def normalizar_url_post_instagram(url: str) -> str:
    """URL canonica com shortcode (ID) do post: .../p/CODE/, .../reel/CODE/ ou .../tv/CODE/."""
    if not url or (isinstance(url, float) and pd.isna(url)):
        return ""
    s = str(url).strip()
    if not s or s.lower() == "nan":
        return ""
    s = s.split("?")[0].split("#")[0].rstrip("/")
    if s.startswith("/"):
        s = "https://www.instagram.com" + s
    elif not re.match(r"^https?://", s, re.I):
        if "instagram.com" in s.lower():
            s = "https://" + s.lstrip("/")
    m = _RE_SHORTCODE_INSTAGRAM.search(s)
    if not m:
        if re.match(r"^https?://(?:www\.)?instagram\.com/?$", s, re.I):
            return ""
        return s
    code = m.group(1)
    lower = s.lower()
    if "/reel" in lower:
        return f"https://www.instagram.com/reel/{code}/"
    if "/tv/" in lower:
        return f"https://www.instagram.com/tv/{code}/"
    return f"https://www.instagram.com/p/{code}/"


def reindexar_por_post_por_shortcode(por_post: dict) -> dict:
    """Unifica entradas do mesmo post (mesmo shortcode) e normaliza URLs gravadas."""
    por_codigo: dict[str, tuple[str, dict]] = {}
    sem_codigo: dict[str, dict] = {}
    for url, usuarios in por_post.items():
        norm = normalizar_url_post_instagram(url)
        codigo = shortcode_post_instagram(norm or url)
        if not codigo:
            if norm:
                sem_codigo[norm] = mesclar_usuarios_no_post(sem_codigo.get(norm, {}), usuarios)
            continue
        if codigo in por_codigo:
            url_antiga, users_antigos = por_codigo[codigo]
            url_escolhida = norm if url_post_tem_shortcode(norm) else url_antiga
            por_codigo[codigo] = (
                url_escolhida,
                mesclar_usuarios_no_post(users_antigos, usuarios),
            )
        else:
            por_codigo[codigo] = (norm, dict(usuarios))
    resultado = dict(sem_codigo)
    for _, (url_canonica, users) in por_codigo.items():
        resultado[url_canonica] = users
    return resultado


def resolver_url_post_instagram(page, log_callback) -> str:
    """
    Obtem URL com ID do post: barra do browser ou links no modal/article visivel.
    No feed o Instagram muitas vezes nao altera page.url ao abrir curtidas.
    """
    norm_dom = ""
    try:
        bruto_dom = safe_page_evaluate(page, _SCRIPT_URL_POST_DOM) or ""
        norm_dom = normalizar_url_post_instagram(bruto_dom)
    except Exception as exc:
        log_callback(f"AVISO: nao foi possivel ler URL do post no HTML: {exc}")

    norm_page = normalizar_url_post_instagram(page.url)
    if url_post_tem_shortcode(norm_dom):
        url_final = norm_dom
    elif url_post_tem_shortcode(norm_page):
        url_final = norm_page
    else:
        log_callback(
            "AVISO: ID do post nao encontrado. Abra o post (permalink /p/... ou /reel/...) "
            "ou o modal de curtidas a partir do post antes de Confirmar."
        )
        return norm_page or norm_dom

    codigo = shortcode_post_instagram(url_final)
    log_callback(f"URL do post (chave): {url_final} | ID: {codigo}")
    return url_final


def _split_int(total: int, n: int) -> list[int]:
    if n <= 0:
        return []
    total = int(total)
    base = total // n
    rem = total % n
    return [base + (1 if i < rem else 0) for i in range(n)]


def caminho_excel_instagram() -> Path:
    return pasta_area_trabalho() / EXCEL_FILE


def caminho_json_legado_instagram() -> Path:
    return pasta_area_trabalho() / POSTS_JSON_FILE


def ler_dataframe_ranking(excel_path: Path) -> pd.DataFrame:
    """Primeira folha legado ou folha 'Ranking'."""
    xl = pd.ExcelFile(excel_path, engine="openpyxl")
    if SHEET_RANKING in xl.sheet_names:
        return pd.read_excel(excel_path, sheet_name=SHEET_RANKING, engine="openpyxl")
    return pd.read_excel(excel_path, sheet_name=0, engine="openpyxl")


def por_post_para_dataframe(por_post: dict) -> pd.DataFrame:
    cols = ["URL_do_Post", "Usuario_Instagram", "Nome_Real", "Qtd_Curtidas", "Qtd_Comentarios"]
    if not por_post:
        return pd.DataFrame(columns=cols)
    linhas = []
    for url, usuarios in por_post.items():
        for usuario, d in usuarios.items():
            linhas.append(
                {
                    "URL_do_Post": url,
                    "Usuario_Instagram": usuario,
                    "Nome_Real": d.get("nome_real") or "",
                    "Qtd_Curtidas": int(d.get("curtidas", 0) or 0),
                    "Qtd_Comentarios": int(d.get("comentarios", 0) or 0),
                }
            )
    return pd.DataFrame(linhas)


def carregar_por_post_da_folha_detalhe(excel_path: Path) -> dict | None:
    """
    Le folha PorPost. Retorna dict se a folha existir e tiver colunas esperadas;
    None se a folha nao existir ou formato invalido (para tentar outros meios).
    """
    xl = pd.ExcelFile(excel_path, engine="openpyxl")
    if SHEET_POR_POST not in xl.sheet_names:
        return None
    dfp = pd.read_excel(excel_path, sheet_name=SHEET_POR_POST, engine="openpyxl")
    colunas = ["URL_do_Post", "Usuario_Instagram", "Qtd_Curtidas", "Qtd_Comentarios"]
    if not all(c in dfp.columns for c in colunas):
        return None
    if dfp.empty:
        return None
    por_post: dict[str, dict[str, dict]] = {}
    for _, row in dfp.iterrows():
        url = normalizar_url_post_instagram(row["URL_do_Post"])
        if not url:
            continue
        usuario = str(row["Usuario_Instagram"]).strip()
        if not usuario or usuario.lower() == "nan":
            continue
        nr = row.get("Nome_Real")
        nome = "" if pd.isna(nr) else str(nr).strip()
        por_post.setdefault(url, {})
        por_post[url][usuario] = {
            "nome_real": nome,
            "curtidas": int(row["Qtd_Curtidas"] or 0),
            "comentarios": int(row["Qtd_Comentarios"] or 0),
        }
    return por_post


def agregar_por_post_em_ranking(por_post: dict) -> dict:
    """Agrega por_post[url][usuario] -> ranking global por usuario."""
    ranking_engajamento = {}
    for post_url, usuarios in por_post.items():
        for usuario, d in usuarios.items():
            ranking_engajamento.setdefault(
                usuario, {"nome_real": "", "curtidas": 0, "comentarios": 0, "urls": set()}
            )
            nome = d.get("nome_real") or ""
            if nome:
                ranking_engajamento[usuario]["nome_real"] = nome
            ranking_engajamento[usuario]["curtidas"] += int(d.get("curtidas", 0) or 0)
            ranking_engajamento[usuario]["comentarios"] += int(d.get("comentarios", 0) or 0)
            ranking_engajamento[usuario]["urls"].add(post_url)
    return ranking_engajamento


def _finalizar_carga_por_post(por_post: dict | None) -> dict:
    if not por_post:
        return {}
    return reindexar_por_post_por_shortcode(por_post)


def carregar_por_post_existente(log_callback) -> dict:
    """
    Carrega estado por URL de post: folha 'PorPost' no xlsx (preferencial),
    depois JSON legado na area de trabalho, depois migracao a partir da folha de ranking.
    """
    excel_path = caminho_excel_instagram()
    json_path = caminho_json_legado_instagram()

    if excel_path.is_file():
        try:
            por_post = carregar_por_post_da_folha_detalhe(excel_path)
            if por_post is not None:
                por_post = _finalizar_carga_por_post(por_post)
                log_callback(
                    f"Estado no Excel ({excel_path.name}, folha {SHEET_POR_POST}): "
                    f"{len(por_post)} post(s). Reprocessar o mesmo URL acrescenta apenas usuarios novos."
                )
                return por_post
        except Exception as exc:
            log_callback(f"AVISO: ao ler folha {SHEET_POR_POST} do Excel: {exc}")

    if json_path.is_file():
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            posts = data.get("posts") or {}
            posts_norm = {}
            for k, v in posts.items():
                nk = normalizar_url_post_instagram(k)
                if nk:
                    posts_norm[nk] = v
            posts = _finalizar_carga_por_post(posts_norm)
            log_callback(
                f"Ficheiro legado {json_path.name} encontrado: {len(posts)} post(s). "
                f"Na proxima gravacao o detalhe passa para o Excel (folha {SHEET_POR_POST}); pode apagar o JSON."
            )
            return posts
        except Exception as exc:
            log_callback(f"AVISO: nao foi possivel ler {json_path}: {exc}")

    if excel_path.is_file():
        try:
            por_post = migrar_excel_para_por_post(excel_path, log_callback)
            por_post = _finalizar_carga_por_post(por_post)
            if por_post:
                log_callback(
                    f"Excel sem folha {SHEET_POR_POST}: importado pela folha de ranking "
                    f"(totais repartidos por URL). A proxima gravacao cria a folha {SHEET_POR_POST} no mesmo ficheiro."
                )
            return por_post
        except Exception as exc:
            log_callback(f"AVISO: nao foi possivel ler Excel existente: {exc}")
    else:
        log_callback("Nenhum relatorio anterior na area de trabalho; ranking comeca vazio.")

    return {}


def migrar_excel_para_por_post(excel_path: Path, log_callback) -> dict:
    df = ler_dataframe_ranking(excel_path)
    colunas = ["Usuario_Instagram", "Nome_Real", "Qtd_Curtidas", "Qtd_Comentarios", "URLs_dos_Posts"]
    if not all(c in df.columns for c in colunas):
        log_callback("AVISO: colunas do Excel nao batem com o formato esperado; migração ignorada.")
        return {}

    por_post: dict[str, dict[str, dict]] = {}
    for _, row in df.iterrows():
        usuario = str(row["Usuario_Instagram"]).strip()
        if not usuario or usuario.lower() == "nan":
            continue
        urls_raw = row["URLs_dos_Posts"]
        if pd.isna(urls_raw):
            continue
        urls = [
            normalizar_url_post_instagram(u)
            for u in str(urls_raw).split(",")
            if u.strip()
        ]
        urls = [u for u in urls if u]
        if not urls:
            continue
        nome = "" if pd.isna(row.get("Nome_Real")) else str(row["Nome_Real"]).strip()
        curtidas = int(row["Qtd_Curtidas"] or 0)
        comentarios = int(row["Qtd_Comentarios"] or 0)
        n = len(urls)
        cv = _split_int(curtidas, n)
        mv = _split_int(comentarios, n)
        for i, url in enumerate(urls):
            por_post.setdefault(url, {})
            por_post[url][usuario] = {
                "nome_real": nome,
                "curtidas": cv[i],
                "comentarios": mv[i],
            }
    return por_post


def merge_contribuicoes_post(
    likes_por_usuario: dict, comentarios_por_usuario: dict
) -> dict[str, dict]:
    """Une curtidas e comentarios de um unico post num mapa usuario -> metricas."""
    post_data: dict[str, dict] = {}
    for usuario, nome_real in likes_por_usuario.items():
        post_data[usuario] = {
            "nome_real": nome_real or "",
            "curtidas": 1,
            "comentarios": 0,
        }
    for usuario in comentarios_por_usuario:
        if usuario not in post_data:
            post_data[usuario] = {"nome_real": "", "curtidas": 0, "comentarios": 0}
        post_data[usuario]["comentarios"] += 1
    return post_data


def mesclar_usuarios_no_post(existente: dict[str, dict], novo: dict[str, dict]) -> dict[str, dict]:
    """
    Mantém usuários já documentados no post e acrescenta apenas os que ainda não existem.
    Para usuários já presentes, preserva métricas e preenche nome_real se estava vazio.
    """
    resultado = {u: dict(d) for u, d in existente.items()}
    for usuario, d in novo.items():
        if usuario not in resultado:
            resultado[usuario] = {
                "nome_real": d.get("nome_real") or "",
                "curtidas": int(d.get("curtidas", 0) or 0),
                "comentarios": int(d.get("comentarios", 0) or 0),
            }
            continue
        antigo = resultado[usuario]
        nome = (antigo.get("nome_real") or "").strip() or (d.get("nome_real") or "").strip()
        resultado[usuario] = {
            "nome_real": nome,
            "curtidas": max(int(antigo.get("curtidas", 0) or 0), int(d.get("curtidas", 0) or 0)),
            "comentarios": max(
                int(antigo.get("comentarios", 0) or 0), int(d.get("comentarios", 0) or 0)
            ),
        }
    return resultado

def safe_page_evaluate(page, script, retries=2, wait_seconds=1.0):
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


def extrair_curtidas(page, log_callback):
    try:
        page.wait_for_selector('div[role="dialog"]:visible', timeout=4000)
    except:
        log_callback("ERRO: A janela de curtidas nao foi detectada na tela.")
        return False, {}

    post_url = page.url 
    log_callback(f"Capturando Usuários e Nomes Reais do link: {post_url}")

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0
    # Agora usamos um dicionário local para guardar { "usuario": "Nome Real" }
    usuarios_coletados_neste_post = {}

    while tentativas_sem_novo_nome < 10:
        
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

        # Rola sempre, mesmo sem novos nomes, para forcar carregar o restante.
        safe_page_evaluate(page, '''() => {
            const modals = document.querySelectorAll('div[role="dialog"]');
            const visibleModal = Array.from(modals).reverse().find(m => m.offsetHeight > 0);
            if (!visibleModal) return;
            
            // 1. Busca exatamente a div com o estilo de rolagem que você encontrou no HTML
            let scrollableDiv = visibleModal.querySelector('div[style*="overflow: hidden auto"], div[style*="overflow-y: auto"]');
            
            // Fallback de segurança caso o Instagram mude o estilo inline
            if (!scrollableDiv) {
                scrollableDiv = Array.from(visibleModal.querySelectorAll('div')).find(
                    el => getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll'
                );
            }
            
            if (scrollableDiv) {
                // 2. No React, alterar o scrollTop diretamente costuma ser mais confiável que o scrollBy
                scrollableDiv.scrollTop += 400;
                
                // 3. O SEGREDO: Dispara um evento fantasma avisando o React que a tela rolou
                // Isso força o Instagram a desenhar as próximas arrobas na tela
                scrollableDiv.dispatchEvent(new Event('scroll', { bubbles: true }));
            }
        }''')
        time.sleep(1.2)

    novas_curtidas = len(usuarios_coletados_neste_post)
    log_callback(f"SUCESSO: {novas_curtidas} contas mapeadas neste post (curtidas).")
    log_callback("Agora vamos para o mapeamento dos comentários...")
    page.keyboard.press("Escape")
    time.sleep(1)
    return True, dict(usuarios_coletados_neste_post)

def extrair_comentarios(page, log_callback):
    try:
        page.wait_for_selector('article', timeout=4000)
    except:
        log_callback("ERRO: O post não foi detectado na tela.")
        return False, set()

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

        # Mesmo comportamento do LinkedIn: rola continuamente ate estabilizar.
        safe_page_evaluate(page, '''() => {
            const articles = document.querySelectorAll('article');
            const visibleArticle = Array.from(articles).reverse().find(a => a.offsetHeight > 0);
            if (!visibleArticle) {
                window.scrollBy(0, 500);
                return;
            }
            const scrollableDiv = Array.from(visibleArticle.querySelectorAll('*')).find(
                el => (getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll') && el.offsetHeight > 100
            );
            if (scrollableDiv) scrollableDiv.scrollBy(0, 500);
            else window.scrollBy(0, 500);
        }''')
        time.sleep(1.2) 

    novas_interacoes = len(usuarios_coletados_neste_post)
    log_callback(f"SUCESSO: {novas_interacoes} comentaristas únicos mapeados neste post.")
    return True, set(usuarios_coletados_neste_post)

def salvar_relatorio(por_post: dict, log_callback):
    ranking_engajamento = agregar_por_post_em_ranking(por_post)
    dados_finais = []
    for usuario, dados in ranking_engajamento.items():
        urls_formatadas = ", ".join(sorted(dados["urls"]))

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
        caminho_excel = caminho_excel_instagram()
        df_por_post = por_post_para_dataframe(por_post)
        # df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        try:
            with pd.ExcelWriter(caminho_excel, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name=SHEET_RANKING, index=False)
                df_por_post.to_excel(writer, sheet_name=SHEET_POR_POST, index=False)
        except PermissionError:
            log_callback(
                "ERRO: nao foi possivel gravar o Excel (ficheiro aberto?). "
                "Feche o ranking no Excel e execute de novo o passo de gravacao."
            )
            raise
        log_callback(f"SUCESSO: {len(dados_finais)} contas unicas no ranking agregado.")
        log_callback(
            f"Gravado: {caminho_excel.resolve()} (folhas {SHEET_RANKING} e {SHEET_POR_POST})."
            # f" e {CSV_FILE} na pasta do projeto."
        )
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
        por_post = carregar_por_post_existente(self.log_callback)
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
                    self.log_callback(f"Sessão ativa detectada. Selecione o post e selecione 'Curtidas' e clique em 'Confirmar'.")
                except:
                    self.log_callback("Login necessário. Por favor, logue no Chrome. Ao finalizar, clique em 'Confirmar'.")
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
                    
                    post_url = resolver_url_post_instagram(page, self.log_callback)

                    self.log_callback(f"Processando curtidas do Post {indice_post}...")
                    sucesso_curtidas, likes_por_usuario = extrair_curtidas(page, self.log_callback)
                    
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
                    sucesso_comentarios, comentaristas = extrair_comentarios(page, self.log_callback)

                    # Finalização do Post atual: acrescenta usuarios novos sem apagar os já documentados
                    if sucesso_curtidas or sucesso_comentarios:
                        if not url_post_tem_shortcode(post_url):
                            post_url = resolver_url_post_instagram(page, self.log_callback)
                        if not url_post_tem_shortcode(post_url):
                            self.log_callback(
                                "ERRO: sem ID na URL do post; este ciclo nao foi gravado. "
                                "Abra o permalink do post (/p/... ou /reel/...) e tente de novo."
                            )
                            continue
                        novo_post = merge_contribuicoes_post(likes_por_usuario, comentaristas)
                        if post_url in por_post:
                            antes = len(por_post[post_url])
                            por_post[post_url] = mesclar_usuarios_no_post(por_post[post_url], novo_post)
                            adicionados = len(por_post[post_url]) - antes
                            self.log_callback(
                                f"Post ja no relatorio: {adicionados} usuario(s) novo(s) "
                                f"({len(por_post[post_url])} no total neste URL)."
                            )
                        else:
                            por_post[post_url] = novo_post
                        contador_posts += 1
                        self.log_callback(f"✅ Post {contador_posts} finalizado com sucesso!")
                        self.log_callback("Pule para o próximo post no Instagram e aguarde o próximo prompt.")

                self.log_callback("Encerrando navegador e salvando dados...")
                if browser:
                    browser.close()
                browser = None

            # Gera o Excel final
            por_post = reindexar_por_post_por_shortcode(por_post)
            salvar_relatorio(por_post, self.log_callback)

        except Exception as exc:
            self.log_callback(f"Erro inesperado no motor: {exc}")
        finally:
            if browser:
                browser.close()
            self.finished_callback()