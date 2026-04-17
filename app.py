"""
Scrape de posts do feed de uma empresa no LinkedIn por PERÍODO DE TEMPO,
incluindo Reações, Comentários e Compartilhamentos (com e sem comentário).
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from playwright.sync_api import Page, sync_playwright

URL = "https://www.linkedin.com/company/houer/posts/?feedView=all&sortBy=RECENT"  # FIX: força ordenação por recentes via query param
DATA_INICIAL = "2026-04-01"  # Formato: YYYY-MM-DD
DATA_FINAL = "2026-04-17"  # Formato: YYYY-MM-DD
STORAGE_STATE = Path(__file__).resolve().parent / "linkedin_storage_state.json"
SCROLL_PAUSE_S = 2.0


def _parse_dias_relativos(tempo_str: str) -> int:
    """Converte strings de tempo do LinkedIn para dias aproximados."""
    t = tempo_str.lower().strip()
    if not t or any(x in t for x in ["agora", "h", "min", "seg"]):
        return 0

    match = re.search(r"(\d+)", t)
    if not match:
        return 0

    val = int(match.group(1))
    if "d" in t: return val
    if "sem" in t or "w" in t: return val * 7
    if "m" in t and "min" not in t: return val * 30
    if "a" in t or "y" in t: return val * 365
    return 0


def _parse_data_range() -> tuple[date, date]:
    """Converte DATA_INICIAL e DATA_FINAL para date e valida intervalo."""
    try:
        data_inicial = date.fromisoformat(DATA_INICIAL)
        data_final = date.fromisoformat(DATA_FINAL)
    except ValueError as e:
        raise ValueError(
            "DATA_INICIAL e DATA_FINAL devem estar no formato YYYY-MM-DD."
        ) from e

    if data_inicial > data_final:
        raise ValueError("DATA_INICIAL não pode ser maior que DATA_FINAL.")

    return data_inicial, data_final


def _estimativa_data_post(tempo_relativo: str) -> date:
    dias = _parse_dias_relativos(tempo_relativo)
    return date.today() - timedelta(days=dias)


# ---------------------------------------------------------------------------
# FIX PRINCIPAL: extrai dados apenas do container raiz do post,
# ignorando sub-elementos de comentários (que também têm data-urn).
# ---------------------------------------------------------------------------
def _extract_post_surface_data(post_el) -> dict:
    """Extrai URL e tempo relativo do post. Comentários são coletados separadamente após expansão."""
    return post_el.evaluate(
        """(el) => {
        const text = (n) => (n && n.innerText ? n.innerText.trim() : "");

        // URL do post
        const link = el.querySelector('a[href*="/posts/"]') || el.querySelector('a[href*="feed/update"]');
        const postUrl = link ? link.href.split("?")[0] : "";

        // Tempo relativo: pega APENAS o primeiro elemento de tempo,
        // que sempre pertence ao post e não a comentários aninhados.
        const timeNode = el.querySelector(
            '.update-components-actor__sub-description-t-black--light span[dir="ltr"], ' +
            '.update-components-actor__sub-description span[aria-hidden="true"]'
        );
        const relativeTime = text(timeNode);

        return { postUrl, relativeTime };
    }"""
    )


def _expand_and_collect_comments(page: Page, post_handle) -> list[str]:
    """
    Clica no CONTADOR de comentários (ex: "12 comentários") para expandir a
    seção de comentários do post, carrega todos via "Ver mais comentários" e
    coleta os nomes dos autores.
    """
    authors: list[str] = []
    try:
        # 1. Clica no contador de comentários — esse é o elemento que EXPANDE a lista,
        #    diferente do botão "Comentar" que apenas abre o campo de digitação.
        comment_count_btn = post_handle.locator(
            'button[aria-label*="comentário"], button[aria-label*="comment"], '
            '.social-details-social-counts__comments button, '
            'button.social-details-social-counts__count-value'
        ).first
        if comment_count_btn.is_visible(timeout=2000):
            comment_count_btn.click(timeout=2000)
            time.sleep(1.5)

        # 2. Clica em "Ver mais comentários" até não haver mais botão
        for _ in range(10):
            load_more = post_handle.locator(
                'button[aria-label*="Carregar comentários anteriores"], '
                'button[aria-label*="Load more comments"], '
                'button.comments-comments-list__load-more-comments-button'
            ).first
            try:
                if load_more.is_visible(timeout=1500):
                    load_more.click(timeout=1500)
                    time.sleep(1.2)
                else:
                    break
            except:
                break

        # 3. Extrai nomes dos autores dos comentários já expandidos na DOM
        authors = post_handle.evaluate(
            """(el) => {
            const names = new Set();
            // Seletores conhecidos para nome do autor de comentário no LinkedIn
            const selectors = [
                '.comments-post-meta__name-text',
                '.comments-comment-meta__description-title',
                '.comments-comment-item__inline-show-more-text + * .comments-post-meta__name-text',
                'article.comments-comment-item .comments-post-meta__name-text'
            ];
            selectors.forEach(sel => {
                el.querySelectorAll(sel).forEach(n => {
                    const t = (n.innerText || "").trim();
                    if (t && t.length >= 2 && t.length <= 120) names.add(t);
                });
            });
            return [...names];
        }"""
        )
    except Exception as e:
        print(f"  [!] Erro ao coletar comentários: {e}")

    return authors


def _force_sort_recentes(page: Page) -> None:
    """
    FIX: Clica no filtro 'Recentes' caso o feed ainda esteja em 'Populares'.
    O parâmetro sortBy=RECENT na URL já tenta isso, mas nem sempre o LinkedIn
    o respeita — então confirmamos clicando no botão na UI também.
    """
    try:
        # Tenta localizar o dropdown de ordenação e clicar em "Recentes"
        sort_btn = page.locator(
            'button[aria-label*="Sort by"], button[aria-label*="Ordenar por"], '
            'button:has-text("Populares"), button:has-text("Top posts")'
        ).first
        if sort_btn.is_visible(timeout=4000):
            sort_btn.click()
            time.sleep(1)
            recent_opt = page.locator(
                'li[aria-label*="Recent"], li:has-text("Recentes"), '
                'div[role="option"]:has-text("Recentes"), div[role="option"]:has-text("Recent")'
            ).first
            if recent_opt.is_visible(timeout=3000):
                recent_opt.click()
                print("[✓] Filtro 'Recentes' aplicado com sucesso.")
                time.sleep(2)
            else:
                print("[!] Opção 'Recentes' não encontrada no dropdown.")
        else:
            print("[i] Botão de ordenação não visível — o feed já pode estar em 'Recentes'.")
    except Exception as e:
        print(f"[!] Não foi possível aplicar filtro 'Recentes': {e}")


def _close_modal(page: Page) -> None:
    try:
        close_btn = page.locator(
            "button[aria-label*='Dismiss'], button[aria-label*='Fechar'], .artdeco-modal__dismiss"
        ).first
        if close_btn.is_visible(timeout=1000):
            close_btn.click(timeout=1000)
    except:
        pass
    page.keyboard.press("Escape")
    time.sleep(0.5)


def _click_modal_and_scroll(page: Page, modal_selector: str = ".artdeco-modal"):
    modal = page.locator(modal_selector).first
    try:
        modal.wait_for(state="visible", timeout=4000)
    except:
        return None

    for _ in range(4):
        try:
            modal.evaluate("""(node) => {
                let scroller = node.querySelector('.artdeco-modal__content');
                if (scroller) scroller.scrollTop = scroller.scrollHeight;
            }""")
            time.sleep(1.0)
        except:
            break
    return modal


def _extract_names_from_modal(modal) -> list[str]:
    if not modal: return []
    names = modal.locator(
        ".text-heading-small, .artdeco-entity-lockup__title, span[dir='ltr']"
    ).all_inner_texts()
    cleaned = []
    for n in names:
        t = (n or "").strip()
        if 2 <= len(t) <= 120 and not re.match(r"^\d+$", t) and t not in cleaned:
            cleaned.append(t)
    return cleaned


# ---------------------------------------------------------------------------
# FIX: restringe os seletores de botão à área de AÇÕES do post (barra inferior),
# usando o container .social-actions ou .feed-shared-social-action-bar,
# evitando clicar em botões de reação dentro de comentários.
# ---------------------------------------------------------------------------
def _get_post_action_bar(post_handle):
    """Retorna o locator da barra de ações do post (reações, comentar, compartilhar)."""
    for selector in [
        ".social-actions",
        ".feed-shared-social-action-bar",
        ".update-components-social-activity",
    ]:
        bar = post_handle.locator(selector).first
        try:
            if bar.is_visible(timeout=500):
                return bar
        except:
            continue
    # Fallback: usa o próprio post_handle
    return post_handle


def _collect_reactions(page: Page, post_handle) -> list[str]:
    names = []
    action_bar = _get_post_action_bar(post_handle)
    try:
        # Clica no CONTADOR de reações (social counts), não no botão de reagir
        trigger = post_handle.locator(
            '.social-details-social-counts__reactions button, '
            'button[aria-label*="reaction"], button[aria-label*="reação"]'
        ).first
        if trigger.is_visible(timeout=2000):
            trigger.click(timeout=2000)
            modal = _click_modal_and_scroll(page)
            names = _extract_names_from_modal(modal)
    except Exception:
        pass
    finally:
        _close_modal(page)
    return names


def _collect_shares(page: Page, post_handle) -> dict:
    out = {"com_comentario": [], "sem_comentario": []}
    try:
        # Clica no CONTADOR de reposts (social counts), não no botão de repostar
        trigger = post_handle.locator(
            '.social-details-social-counts__reshares button, '
            'button[aria-label*="repost"], button[aria-label*="compartilhamento"]'
        ).first
        if trigger.is_visible(timeout=2000):
            trigger.click(timeout=2000)
            time.sleep(1.5)

            modal_visivel = page.locator(".artdeco-modal").first.is_visible(timeout=3000)
            if modal_visivel:
                tabs = page.locator('.artdeco-modal button[role="tab"]').all()
                if len(tabs) >= 2:
                    for tab in tabs:
                        tab_name = tab.inner_text().lower()
                        tab.click()
                        time.sleep(1)
                        modal = _click_modal_and_scroll(page)
                        names = _extract_names_from_modal(modal)
                        if "pensamento" in tab_name or "thought" in tab_name or "coment" in tab_name:
                            out["com_comentario"] = names
                        else:
                            out["sem_comentario"] = names
                else:
                    modal = _click_modal_and_scroll(page)
                    out["sem_comentario"] = _extract_names_from_modal(modal)
    except Exception:
        pass
    finally:
        _close_modal(page)
    return out


def scrape_company_posts(headless: bool = False) -> list[dict]:
    rows: list[dict] = []
    processed_urns = set()
    atingiu_limite_tempo = False
    scrolls_vazios = 0
    data_inicial, data_final = _parse_data_range()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chrome")
        ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
        if STORAGE_STATE.is_file():
            ctx_opts["storage_state"] = str(STORAGE_STATE)

        context = browser.new_context(**ctx_opts)
        page = context.new_page()

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
            print("\n[!] O LinkedIn está pedindo login. Indo para a tela de acesso oficial...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

            print("\n" + "=" * 60)
            print("⏰ O SCRIPT ESTÁ PAUSADO PARA VOCÊ FAZER O LOGIN!")
            print("1. Vá até a janela do Chrome que o robô acabou de abrir.")
            print("2. Digite seu e-mail, senha e passe por qualquer verificação.")
            print("3. Quando você estiver logado e vendo o seu Feed do LinkedIn...")
            input("👉 VOLTE AQUI NO TERMINAL E APERTE A TECLA 'ENTER' PARA CONTINUAR: ")
            print("=" * 60 + "\n")

            time.sleep(3)

            print("Retornando para o feed da empresa...")
            try:
                page.goto(URL, wait_until="domcontentloaded")
            except Exception:
                print("Redirecionamento do LinkedIn em andamento... Forçando a ida para a página da empresa.")
                time.sleep(3)
                page.goto(URL, wait_until="domcontentloaded")

            time.sleep(4)

        # FIX: garante que o feed está ordenado por "Recentes"
        _force_sort_recentes(page)

        print(
            "Iniciando raspagem no intervalo "
            f"{data_inicial.isoformat()} até {data_final.isoformat()}..."
        )

        while not atingiu_limite_tempo:
            # FIX: seleciona apenas os posts de NÍVEL RAIZ (não aninhados dentro de outros posts/comentários)
            post_elements = page.locator(
                "div[data-urn*='activity']:not([data-urn*='activity'] [data-urn*='activity'])"
            ).all()
            novos_nesta_rodada = 0

            for post in post_elements:
                urn = post.get_attribute("data-urn")
                if not urn or urn in processed_urns:
                    continue

                try:
                    post.scroll_into_view_if_needed(timeout=3000)
                    time.sleep(0.5)
                except:
                    continue

                surface = _extract_post_surface_data(post)
                idade_str = surface.get("relativeTime", "")
                data_post = _estimativa_data_post(idade_str)

                if data_post < data_inicial:
                    print(
                        f"\n[!] Post fora do intervalo (mais antigo que {data_inicial.isoformat()}) "
                        f"[{idade_str}]. Encerrando a coleta."
                    )
                    atingiu_limite_tempo = True
                    break
                if data_post > data_final:
                    processed_urns.add(urn)
                    continue

                processed_urns.add(urn)
                novos_nesta_rodada += 1
                post_url = surface.get("postUrl") or urn

                reactions = _collect_reactions(page, post)
                shares = _collect_shares(page, post)
                comment_authors = _expand_and_collect_comments(page, post)

                rows.append({
                    "post_url": post_url,
                    "tempo_relativo": idade_str,
                    "data_post_estimada": data_post.isoformat(),
                    "reacoes_usuarios": reactions,
                    "comentarios_usuarios": comment_authors,
                    "shares_com_comentario": shares["com_comentario"],
                    "shares_sem_comentario": shares["sem_comentario"],
                })

                print(
                    f"Processado post há '{idade_str}' | "
                    f"{len(reactions)} Reações | "
                    f"{len(comment_authors)} Comentários | "
                    f"{len(shares['com_comentario']) + len(shares['sem_comentario'])} Reposts"
                )

            if atingiu_limite_tempo:
                break

            if novos_nesta_rodada == 0:
                scrolls_vazios += 1
                if scrolls_vazios >= 3:
                    print("\n[!] Nenhum post novo encontrado após múltiplos scrolls. Fim do feed atingido.")
                    break
            else:
                scrolls_vazios = 0

            page.evaluate("window.scrollBy(0, window.innerHeight * 1.5);")
            time.sleep(SCROLL_PAUSE_S)

        context.storage_state(path=str(STORAGE_STATE))
        browser.close()

    return rows


def main() -> None:
    data = scrape_company_posts(headless=False)

    if not data:
        print("Nenhum dado retornado. O script não encontrou posts.")
        return

    user_stats = defaultdict(lambda: {
        "qtd_interacoes": 0, "qtd_comentarios": 0,
        "qtd_comp_com_coment": 0, "qtd_comp_sem_coment": 0, "_posts_set": set()
    })

    for row in data:
        post_key = row["post_url"]

        for user in row["reacoes_usuarios"]:
            if user.strip():
                user_stats[user.strip()]["qtd_interacoes"] += 1
                user_stats[user.strip()]["_posts_set"].add(post_key)

        for user in row["comentarios_usuarios"]:
            if user.strip():
                user_stats[user.strip()]["qtd_comentarios"] += 1
                user_stats[user.strip()]["_posts_set"].add(post_key)

        for user in row["shares_com_comentario"]:
            if user.strip():
                user_stats[user.strip()]["qtd_comp_com_coment"] += 1
                user_stats[user.strip()]["_posts_set"].add(post_key)

        for user in row["shares_sem_comentario"]:
            if user.strip():
                user_stats[user.strip()]["qtd_comp_sem_coment"] += 1
                user_stats[user.strip()]["_posts_set"].add(post_key)

    aggregated_rows = []
    for username, stats in user_stats.items():
        aggregated_rows.append({
            "Nome do usuario": username,
            "Qtd_Reacoes": stats["qtd_interacoes"],
            "Qtd_Comentarios": stats["qtd_comentarios"],
            "Qtd_Compartilhamentos_Com_Comentario": stats["qtd_comp_com_coment"],
            "Qtd_Compartilhamentos_Sem_Comentario": stats["qtd_comp_sem_coment"],
            "Qtd_Total_Posts_Interagidos": len(stats["_posts_set"]),
        })

    df = pd.DataFrame(aggregated_rows).sort_values(
        by=["Qtd_Total_Posts_Interagidos", "Qtd_Reacoes"], ascending=[False, False]
    )

    out_dir = Path(__file__).resolve().parent
    df.to_csv(out_dir / "linkedin_interacoes.csv", sep=";", index=False, encoding="utf-8-sig")
    df.to_excel(out_dir / "linkedin_interacoes.xlsx", index=False)

    print(f"\nSucesso! Relatórios gerados em CSV e XLSX na pasta: {out_dir}")


if __name__ == "__main__":
    main()