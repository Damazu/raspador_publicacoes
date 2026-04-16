"""
Scrape de posts do feed de uma empresa no LinkedIn por PERÍODO DE TEMPO,
incluindo Reações, Comentários e Compartilhamentos (com e sem comentário).
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd
from playwright.sync_api import Page, sync_playwright

URL = "https://www.linkedin.com/company/houer/posts/?feedView=all"
MAX_DIAS = 10  # Limite de tempo (ex: buscar posts dos últimos 10 dias)
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


def _extract_post_surface_data(post_el) -> dict:
    return post_el.evaluate(
        """(el) => {
        const text = (n) => (n && n.innerText ? n.innerText.trim() : "");
        const link = el.querySelector('a[href*="/posts/"]') || el.querySelector('a[href*="feed/update"]');
        const postUrl = link ? link.href.split("?")[0] : "";
        const timeNode = el.querySelector('.update-components-actor__sub-description-t-black--light span[dir="ltr"], .update-components-actor__sub-description span[aria-hidden="true"]');
        const relativeTime = text(timeNode);
        const commentAuthors = [];
        el.querySelectorAll('.comments-post-meta__name-text, .comments-comment-meta__description-title').forEach((n) => {
          const name = text(n);
          if (name && name.length < 200) commentAuthors.push(name);
        });
        return { postUrl, relativeTime, commentAuthors: [...new Set(commentAuthors)] };
      }"""
    )


def _close_modal(page: Page) -> None:
    """Garante de forma agressiva que qualquer modal aberto seja fechado para não travar o scroll."""
    try:
        close_btn = page.locator("button[aria-label*='Dismiss'], button[aria-label*='Fechar'], .artdeco-modal__dismiss").first
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
    names = modal.locator(".text-heading-small, .artdeco-entity-lockup__title, span[dir='ltr']").all_inner_texts()
    cleaned = []
    for n in names:
        t = (n or "").strip()
        if 2 <= len(t) <= 120 and not re.match(r"^\d+$", t) and t not in cleaned:
            cleaned.append(t)
    return cleaned


def _collect_reactions(page: Page, post_handle) -> list[str]:
    names = []
    try:
        trigger = post_handle.locator('button[aria-label*="reaction"], button[aria-label*="reação"]').first
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
        trigger = post_handle.locator('button[aria-label*="repost"], button[aria-label*="compartilhamento"], button:has-text("repost")').first
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

    with sync_playwright() as p:
        # Usa o canal "chrome" oficial do seu computador
        browser = p.chromium.launch(headless=headless, channel="chrome")
        ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
        if STORAGE_STATE.is_file():
            ctx_opts["storage_state"] = str(STORAGE_STATE)

        context = browser.new_context(**ctx_opts)
        page = context.new_page()
        
        # 1. Tenta acessar a página da empresa diretamente
        page.goto(URL, wait_until="domcontentloaded")
        time.sleep(4)
        
        # 2. Verificação inteligente: Checa URL ou a presença de botões de login
        precisa_logar = False
        if "signup" in page.url or "authwall" in page.url or "login" in page.url:
            precisa_logar = True
        elif page.locator('a[href*="/login"], button:has-text("Entrar"), button:has-text("Sign in")').first.is_visible(timeout=3000):
            precisa_logar = True

        if precisa_logar:
            print("\n[!] O LinkedIn está pedindo login. Indo para a tela de acesso oficial...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            
            # --- PAUSA INFINITA PARA O USUÁRIO ---
            print("\n" + "="*60)
            print("⏰ O SCRIPT ESTÁ PAUSADO PARA VOCÊ FAZER O LOGIN!")
            print("1. Vá até a janela do Chrome que o robô acabou de abrir.")
            print("2. Digite seu e-mail, senha e passe por qualquer verificação.")
            print("3. Quando você estiver logado e vendo o seu Feed do LinkedIn...")
            input("👉 VOLTE AQUI NO TERMINAL E APERTE A TECLA 'ENTER' PARA CONTINUAR: ")
            print("="*60 + "\n")
            
            # Dá um tempo para o navegador "respirar" e terminar os próprios redirecionamentos do LinkedIn
            time.sleep(3)
            
            # Após logar, volta para a URL original da empresa
            print("Retornando para o feed da empresa...")
            try:
                page.goto(URL, wait_until="domcontentloaded")
            except Exception:
                # Se colidir com o redirecionamento automático do LinkedIn, espera mais um pouco e tenta de novo
                print("Redirecionamento do LinkedIn em andamento... Forçando a ida para a página da empresa.")
                time.sleep(3)
                page.goto(URL, wait_until="domcontentloaded")
                
            time.sleep(4)

        print(f"Iniciando raspagem até o limite de {MAX_DIAS} dias...")

        while not atingiu_limite_tempo:
            post_elements = page.locator("div[data-urn*='activity']").all()
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
                dias_post = _parse_dias_relativos(idade_str)

                if dias_post > MAX_DIAS:
                    print(f"\n[!] Post atingiu o limite de {MAX_DIAS} dias ({idade_str}). Encerrando a coleta.")
                    atingiu_limite_tempo = True
                    break

                processed_urns.add(urn)
                novos_nesta_rodada += 1
                post_url = surface.get("postUrl") or urn

                try:
                    btn = post.locator('button[aria-label*="Comentar"], button[aria-label*="Comment"]').first
                    if btn.is_visible(timeout=1000): 
                        btn.click(timeout=1000)
                        time.sleep(1)
                except: pass

                reactions = _collect_reactions(page, post)
                shares = _collect_shares(page, post)

                rows.append({
                    "post_url": post_url,
                    "tempo_relativo": idade_str,
                    "reacoes_usuarios": reactions,
                    "comentarios_usuarios": surface.get("commentAuthors", []),
                    "shares_com_comentario": shares["com_comentario"],
                    "shares_sem_comentario": shares["sem_comentario"],
                })
                
                print(f"Processado post há '{idade_str}' | {len(reactions)} Reações | {len(shares['com_comentario']) + len(shares['sem_comentario'])} Reposts")

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

        # Salva o login para a próxima execução
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