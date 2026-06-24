import re
import threading
import time
from pathlib import Path

import pandas as pd
from paths_utils import caminho_estado_sessao, pasta_area_trabalho
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

URL = "https://www.linkedin.com/feed/"
EXCEL_FILE = "ranking_engajamento_linkedin.xlsx"
# CSV_FILE = "ranking_engajamento_linkedin.csv"
SHEET_RANKING = "Ranking"
SHEET_POR_POST = "PorPost"
STORAGE_STATE = caminho_estado_sessao("linkedin_state.json")

_RE_URN_ACTIVITY = re.compile(r"urn:li:activity:(\d+)", re.IGNORECASE)
_METRICAS_PESSOA = (
    "reacoes",
    "comentarios",
    "compartilhamentos_com_pensamentos",
    "compartilhamentos_sem_pensamentos",
)


def pessoa_metricas_vazia() -> dict:
    return {k: 0 for k in _METRICAS_PESSOA}


def urn_atividade_linkedin(url: str) -> str:
    if not url or (isinstance(url, float) and pd.isna(url)):
        return ""
    m = _RE_URN_ACTIVITY.search(str(url).strip())
    return m.group(1) if m else ""


def url_post_tem_urn(url: str) -> bool:
    return bool(urn_atividade_linkedin(url))


def normalizar_url_post_linkedin(url: str) -> str:
    """URL canonica com URN do post: .../feed/update/urn:li:activity:ID/."""
    if not url or (isinstance(url, float) and pd.isna(url)):
        return ""
    s = str(url).strip()
    if not s or s.lower() in ("nan", "url nao identificada"):
        return ""
    s = s.split("?")[0].split("#")[0].rstrip("/")
    activity_id = urn_atividade_linkedin(s)
    if activity_id:
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"
    if re.match(r"^https?://(?:[\w-]+\.)?linkedin\.com/?$", s, re.I):
        return ""
    return s


def _split_int(total: int, n: int) -> list[int]:
    if n <= 0:
        return []
    total = int(total)
    base = total // n
    rem = total % n
    return [base + (1 if i < rem else 0) for i in range(n)]


def caminho_excel_linkedin() -> Path:
    return pasta_area_trabalho() / EXCEL_FILE


def ler_dataframe_ranking(excel_path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(excel_path, engine="openpyxl")
    if SHEET_RANKING in xl.sheet_names:
        return pd.read_excel(excel_path, sheet_name=SHEET_RANKING, engine="openpyxl")
    return pd.read_excel(excel_path, sheet_name=0, engine="openpyxl")


def por_post_para_dataframe(por_post: dict) -> pd.DataFrame:
    cols = [
        "URL_do_Post",
        "Nome",
        "Qtd_Reacoes",
        "Qtd_Comentarios",
        "Qtd_Compartilhamentos_Com_Pensamentos",
        "Qtd_Compartilhamentos_Sem_Pensamentos",
    ]
    if not por_post:
        return pd.DataFrame(columns=cols)
    linhas = []
    for url, pessoas in por_post.items():
        for nome, d in pessoas.items():
            linhas.append(
                {
                    "URL_do_Post": url,
                    "Nome": nome,
                    "Qtd_Reacoes": int(d.get("reacoes", 0) or 0),
                    "Qtd_Comentarios": int(d.get("comentarios", 0) or 0),
                    "Qtd_Compartilhamentos_Com_Pensamentos": int(
                        d.get("compartilhamentos_com_pensamentos", 0) or 0
                    ),
                    "Qtd_Compartilhamentos_Sem_Pensamentos": int(
                        d.get("compartilhamentos_sem_pensamentos", 0) or 0
                    ),
                }
            )
    return pd.DataFrame(linhas)


def carregar_por_post_da_folha_detalhe(excel_path: Path) -> dict | None:
    xl = pd.ExcelFile(excel_path, engine="openpyxl")
    if SHEET_POR_POST not in xl.sheet_names:
        return None
    dfp = pd.read_excel(excel_path, sheet_name=SHEET_POR_POST, engine="openpyxl")
    colunas = ["URL_do_Post", "Nome", "Qtd_Reacoes", "Qtd_Comentarios"]
    if not all(c in dfp.columns for c in colunas):
        return None
    if dfp.empty:
        return None
    por_post: dict[str, dict[str, dict]] = {}
    for _, row in dfp.iterrows():
        url = normalizar_url_post_linkedin(row["URL_do_Post"])
        if not url:
            continue
        nome = str(row["Nome"]).strip()
        if not nome or nome.lower() == "nan":
            continue
        por_post.setdefault(url, {})
        por_post[url][nome] = {
            "reacoes": int(row["Qtd_Reacoes"] or 0),
            "comentarios": int(row["Qtd_Comentarios"] or 0),
            "compartilhamentos_com_pensamentos": int(
                row.get("Qtd_Compartilhamentos_Com_Pensamentos", 0) or 0
            ),
            "compartilhamentos_sem_pensamentos": int(
                row.get("Qtd_Compartilhamentos_Sem_Pensamentos", 0) or 0
            ),
        }
    return por_post


def agregar_por_post_em_ranking(por_post: dict) -> dict:
    ranking = {}
    for post_url, pessoas in por_post.items():
        for nome, d in pessoas.items():
            ranking.setdefault(
                nome,
                {
                    "reacoes": 0,
                    "comentarios": 0,
                    "compartilhamentos_com_pensamentos": 0,
                    "compartilhamentos_sem_pensamentos": 0,
                    "urls": set(),
                },
            )
            for k in _METRICAS_PESSOA:
                ranking[nome][k] += int(d.get(k, 0) or 0)
            ranking[nome]["urls"].add(post_url)
    return ranking


def mesclar_pessoas_no_post(existente: dict[str, dict], novo: dict[str, dict]) -> dict[str, dict]:
    """Mantém pessoas já documentadas e acrescenta apenas as novas (métricas: máximo por tipo)."""
    resultado = {n: dict(d) for n, d in existente.items()}
    for nome, d in novo.items():
        if nome not in resultado:
            resultado[nome] = {k: int(d.get(k, 0) or 0) for k in _METRICAS_PESSOA}
            continue
        antigo = resultado[nome]
        resultado[nome] = {
            k: max(int(antigo.get(k, 0) or 0), int(d.get(k, 0) or 0)) for k in _METRICAS_PESSOA
        }
    return resultado


def merge_contribuicoes_post_linkedin(
    reacoes: list[str],
    comentarios: list[str],
    compartilhamentos: dict[str, dict],
) -> dict[str, dict]:
    post_data: dict[str, dict] = {}
    for nome in reacoes:
        nome = nome.strip()
        if not nome:
            continue
        post_data.setdefault(nome, pessoa_metricas_vazia())
        post_data[nome]["reacoes"] = 1
    for nome in comentarios:
        nome = nome.strip()
        if not nome:
            continue
        post_data.setdefault(nome, pessoa_metricas_vazia())
        post_data[nome]["comentarios"] = 1
    for nome, d in compartilhamentos.items():
        nome = nome.strip()
        if not nome:
            continue
        post_data.setdefault(nome, pessoa_metricas_vazia())
        post_data[nome]["compartilhamentos_com_pensamentos"] = max(
            post_data[nome]["compartilhamentos_com_pensamentos"],
            int(d.get("compartilhamentos_com_pensamentos", 0) or 0),
        )
        post_data[nome]["compartilhamentos_sem_pensamentos"] = max(
            post_data[nome]["compartilhamentos_sem_pensamentos"],
            int(d.get("compartilhamentos_sem_pensamentos", 0) or 0),
        )
    return post_data


def reindexar_por_post_por_urn(por_post: dict) -> dict:
    por_urn: dict[str, tuple[str, dict]] = {}
    sem_urn: dict[str, dict] = {}
    for url, pessoas in por_post.items():
        norm = normalizar_url_post_linkedin(url)
        urn = urn_atividade_linkedin(norm or url)
        if not urn:
            if norm:
                sem_urn[norm] = mesclar_pessoas_no_post(sem_urn.get(norm, {}), pessoas)
            continue
        if urn in por_urn:
            url_antiga, pessoas_antigas = por_urn[urn]
            url_escolhida = norm if url_post_tem_urn(norm) else url_antiga
            por_urn[urn] = (url_escolhida, mesclar_pessoas_no_post(pessoas_antigas, pessoas))
        else:
            por_urn[urn] = (norm, dict(pessoas))
    resultado = dict(sem_urn)
    for _, (url_canonica, pessoas) in por_urn.items():
        resultado[url_canonica] = pessoas
    return resultado


def migrar_excel_para_por_post(excel_path: Path, log_callback) -> dict:
    df = ler_dataframe_ranking(excel_path)
    colunas = [
        "nome",
        "Qtd_Reacoes",
        "Qtd_Comentarios",
        "Qtd_Compartilhamentos_Com_Pensamentos",
        "Qtd_Compartilhamentos_Sem_Pensamentos",
        "URLs_dos_Posts",
    ]
    if not all(c in df.columns for c in colunas):
        log_callback("AVISO: colunas do Excel nao batem com o formato esperado; migracao ignorada.")
        return {}

    por_post: dict[str, dict[str, dict]] = {}
    for _, row in df.iterrows():
        nome = str(row["nome"]).strip()
        if not nome or nome.lower() == "nan":
            continue
        urls_raw = row["URLs_dos_Posts"]
        if pd.isna(urls_raw):
            continue
        urls = [
            normalizar_url_post_linkedin(u)
            for u in str(urls_raw).split(",")
            if u.strip()
        ]
        urls = [u for u in urls if u]
        if not urls:
            continue
        n = len(urls)
        rv = _split_int(int(row["Qtd_Reacoes"] or 0), n)
        cv = _split_int(int(row["Qtd_Comentarios"] or 0), n)
        scv = _split_int(int(row["Qtd_Compartilhamentos_Com_Pensamentos"] or 0), n)
        ssv = _split_int(int(row["Qtd_Compartilhamentos_Sem_Pensamentos"] or 0), n)
        for i, url in enumerate(urls):
            por_post.setdefault(url, {})
            por_post[url][nome] = {
                "reacoes": rv[i],
                "comentarios": cv[i],
                "compartilhamentos_com_pensamentos": scv[i],
                "compartilhamentos_sem_pensamentos": ssv[i],
            }
    return por_post


def _finalizar_carga_por_post(por_post: dict | None) -> dict:
    if not por_post:
        return {}
    return reindexar_por_post_por_urn(por_post)


def carregar_por_post_existente(log_callback) -> dict:
    excel_path = caminho_excel_linkedin()
    if excel_path.is_file():
        try:
            por_post = carregar_por_post_da_folha_detalhe(excel_path)
            if por_post is not None:
                por_post = _finalizar_carga_por_post(por_post)
                log_callback(
                    f"Estado no Excel ({excel_path.name}, folha {SHEET_POR_POST}): "
                    f"{len(por_post)} post(s). Reprocessar o mesmo URL acrescenta apenas pessoas novas."
                )
                return por_post
        except Exception as exc:
            log_callback(f"AVISO: ao ler folha {SHEET_POR_POST} do Excel: {exc}")

        try:
            por_post = migrar_excel_para_por_post(excel_path, log_callback)
            por_post = _finalizar_carga_por_post(por_post)
            if por_post:
                log_callback(
                    f"Excel sem folha {SHEET_POR_POST}: importado pela folha de ranking. "
                    f"A proxima gravacao cria a folha {SHEET_POR_POST} no mesmo ficheiro."
                )
            return por_post
        except Exception as exc:
            log_callback(f"AVISO: nao foi possivel ler Excel existente: {exc}")
    else:
        log_callback("Nenhum relatorio anterior na area de trabalho; ranking comeca vazio.")
    return {}

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
        const candidatos = [];
        const seletores = [
            "motiondialog div[data-urn*='activity']",
            "div[role='dialog'] div[data-urn*='activity']",
            "div[data-urn*='activity']:not([data-urn*='activity'] [data-urn*='activity'])",
        ];
        for (const sel of seletores) {
            document.querySelectorAll(sel).forEach(el => candidatos.push(el));
        }
        let posts = candidatos;
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
        if not str(urn).startswith("urn:"):
            urn = f"urn:li:activity:{urn}"
        return normalizar_url_post_linkedin(f"https://www.linkedin.com/feed/update/{urn}/")
    return ""


def resolver_url_post_linkedin(page, log_callback) -> str:
    norm_dom = normalizar_url_post_linkedin(obter_url_post_ativo(page))
    norm_page = normalizar_url_post_linkedin(page.url)
    if url_post_tem_urn(norm_dom):
        url_final = norm_dom
    elif url_post_tem_urn(norm_page):
        url_final = norm_page
    else:
        log_callback(
            "AVISO: URN do post nao encontrada. Role o post para o centro da tela "
            "ou abra o modal de reacoes a partir do post antes de Confirmar."
        )
        return norm_dom or norm_page

    urn = urn_atividade_linkedin(url_final)
    log_callback(f"URL do post (chave): {url_final} | URN: urn:li:activity:{urn}")
    return url_final


def extrair_reacoes(page, log_callback):
    base_modal_selector = "div[role='dialog'].social-details-reactors-modal"
    modal = page.locator(base_modal_selector).first

    if not modal.is_visible():
        log_callback("ERRO: A janela de reacoes nao esta aberta.")
        return False, []

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
    nomes: list[str] = []
    vistos: set[str] = set()

    for texto in elementos_nome:
        nome_limpo = texto.split("\n")[0].strip()
        if nome_limpo and nome_limpo not in vistos:
            vistos.add(nome_limpo)
            nomes.append(nome_limpo)

    log_callback(f"{len(nomes)} reacoes mapeadas neste post.")
    log_callback("Abra a proxima janela de reacoes e clique em Confirmar para continuar.")
    page.keyboard.press("Escape")
    time.sleep(1)
    return True, nomes


def extrair_compartilhamentos(page, log_callback):
    # 1. Atualizado para a classe específica do modal de compartilhamentos (Reposts)
    base_modal_selector = "div[role='dialog'].feed-modals-reposts-modal"
    
    try:
        log_callback("Aguardando a janela de compartilhamentos abrir...")
        # Usamos wait_for_selector para maior estabilidade, igual recomendado antes
        page.wait_for_selector(base_modal_selector, state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        log_callback("ERRO: A janela de compartilhamentos nao esta aberta.")
        return False, {}

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
    vistos: set[str] = set()
    compartilhamentos: dict[str, dict] = {}
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

        compartilhamentos.setdefault(nome_limpo, pessoa_metricas_vazia())
        if possui_pensamento:
            compartilhamentos[nome_limpo]["compartilhamentos_com_pensamentos"] = 1
            com_pensamentos += 1
        else:
            compartilhamentos[nome_limpo]["compartilhamentos_sem_pensamentos"] = 1
            sem_pensamentos += 1
        vistos.add(nome_limpo)

    # 5. Finalização
    log_callback(
        f"Compartilhamentos mapeados: {com_pensamentos} com pensamentos e {sem_pensamentos} sem pensamentos."
    )
    log_callback("Abra a proxima janela de compartilhamentos e clique em Confirmar para continuar.")
    
    # Fecha o modal suavemente
    page.keyboard.press("Escape")
    time.sleep(1)

    return True, compartilhamentos


def extrair_comentarios(page, post_url, log_callback):
    try:
        log_callback("Iniciando raspagem de comentarios estrutural...")

        urn_alvo = ""
        activity_id = urn_atividade_linkedin(post_url)
        if activity_id:
            urn_alvo = f"urn:li:activity:{activity_id}"

        if not urn_alvo:
            log_callback("ERRO: Nao foi possivel identificar a URN do post. Abortando extracao.")
            return False, []

        usuarios_coletados_neste_post = set()
        pessoas_carregadas = 0
        tentativas_sem_novo_nome = 0

        safe_page_evaluate(page, "window.scrollBy(0, 200);")
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

        comentarios = sorted(usuarios_coletados_neste_post)
        log_callback(f"SUCESSO: {len(comentarios)} comentarios unicos mapeados neste post.")
        return True, comentarios

    except Exception as e:
        log_callback(f"Erro ao extrair comentarios: {e}")
        return False, []


def salvar_relatorio(por_post: dict, log_callback):
    ranking_engajamento = agregar_por_post_em_ranking(por_post)
    dados_finais = []
    for nome, dados in ranking_engajamento.items():
        total_engajamento = sum(int(dados[k] or 0) for k in _METRICAS_PESSOA)
        urls_formatadas = ", ".join(sorted(dados["urls"]))
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
        caminho_excel = caminho_excel_linkedin()
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
        log_callback(f"SUCESSO: {len(dados_finais)} pessoas no ranking agregado.")
        log_callback(
            f"Gravado: {caminho_excel.resolve()} (folhas {SHEET_RANKING} e {SHEET_POR_POST})."
            # f" e {CSV_FILE} na pasta do projeto."
        )
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
        por_post = carregar_por_post_existente(self.log_callback)
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

                    post_url = resolver_url_post_linkedin(page, self.log_callback)
                    sucesso_reacoes, reacoes = extrair_reacoes(page, self.log_callback)
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

                    sucesso_comentarios, comentarios = extrair_comentarios(page, post_url, self.log_callback)
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

                    sucesso_compartilhamentos, compartilhamentos = extrair_compartilhamentos(
                        page, self.log_callback
                    )

                    if sucesso_reacoes or sucesso_comentarios or sucesso_compartilhamentos:
                        if not url_post_tem_urn(post_url):
                            post_url = resolver_url_post_linkedin(page, self.log_callback)
                        if not url_post_tem_urn(post_url):
                            self.log_callback(
                                "ERRO: sem URN na URL do post; este ciclo nao foi gravado. "
                                "Role o post para o centro ou abra o modal a partir do post."
                            )
                        else:
                            novo_post = merge_contribuicoes_post_linkedin(
                                reacoes if sucesso_reacoes else [],
                                comentarios if sucesso_comentarios else [],
                                compartilhamentos if sucesso_compartilhamentos else {},
                            )
                            if post_url in por_post:
                                antes = len(por_post[post_url])
                                por_post[post_url] = mesclar_pessoas_no_post(
                                    por_post[post_url], novo_post
                                )
                                adicionados = len(por_post[post_url]) - antes
                                self.log_callback(
                                    f"Post ja no relatorio: {adicionados} pessoa(s) nova(s) "
                                    f"({len(por_post[post_url])} no total neste URL)."
                                )
                            else:
                                por_post[post_url] = novo_post
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

            por_post = reindexar_por_post_por_urn(por_post)
            salvar_relatorio(por_post, self.log_callback)
            
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
