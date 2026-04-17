from playwright.sync_api import sync_playwright
import pandas as pd
import time
import os
from pathlib import Path

# --- CONFIGURAÇÕES ---
URL = "https://www.linkedin.com/company/houer/posts/?feedView=all&sortBy=RECENT"
csv_file = "ranking_engajamento_manual.csv"
STORAGE_STATE = Path("linkedin_state.json")

def scrape_interativo():
    # Dicionário mestre que vai acumular os dados
    ranking_reacoes = {}

    with sync_playwright() as p:
        # headless=False é obrigatório aqui para você poder ver a tela e clicar
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
        
        if STORAGE_STATE.is_file():
            ctx_opts["storage_state"] = str(STORAGE_STATE)

        context = browser.new_context(**ctx_opts)
        page = context.new_page()

        print(f"Acessando: {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        time.sleep(4)

        # ==============================================================
        # LOGIN (Mesma lógica de segurança)
        # ==============================================================
        precisa_logar = False
        if "signup" in page.url or "authwall" in page.url or "login" in page.url:
            precisa_logar = True
        elif page.locator('a[href*="/login"], button:has-text("Entrar"), button:has-text("Sign in")').first.is_visible(timeout=3000):
            precisa_logar = True

        if precisa_logar:
            print("\n[!] O LinkedIn está pedindo login. Indo para a tela de acesso...")
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            print("⏰ FAÇA O LOGIN! Depois que carregar o Feed, aperte ENTER aqui.")
            input("👉 APERTE A TECLA 'ENTER' PARA CONTINUAR: ")
            time.sleep(5)
            try:
                page.goto(URL, wait_until="domcontentloaded")
            except Exception:
                time.sleep(3)
                page.goto(URL, wait_until="domcontentloaded")
            time.sleep(4)

        context.storage_state(path=str(STORAGE_STATE))
        # ==============================================================

        print("\n" + "="*60)
        print("🤖 MODO SEMI-AUTOMÁTICO ATIVADO!")
        print("COMO USAR:")
        print("1. No navegador, role até o post que desejar.")
        print("2. Clique no número de reações para abrir a janelinha de likes.")
        print("3. Volte aqui no terminal e aperte apenas ENTER.")
        print("4. O robô extrai tudo, fecha a janela e aguarda você ir pro próximo post.")
        print("👉 Quando terminar todos os posts que deseja, digite 'sair' e aperte ENTER.")
        print("="*60 + "\n")

        # --- LOOP INFINITO DE INTERAÇÃO COM O USUÁRIO ---
        # --- LOOP INFINITO DE INTERAÇÃO COM O USUÁRIO ---
        contador_posts = 0

        while True:
            comando = input(f"👉 [Post {contador_posts + 1}] Janela aberta? Aperte ENTER para sugar (ou digite 'sair'): ").strip().lower()

            if comando == 'sair':
                break

            # --- CORREÇÃO AQUI: Seletor muito mais específico para ignorar vídeos ---
            base_modal_selector = "div[role='dialog'].social-details-reactors-modal"
            modal = page.locator(base_modal_selector).first
            
            if not modal.is_visible():
                print("❌ ERRO: A janela de curtidas não está aberta! Clique nas curtidas no navegador e tente de novo.")
                continue

            print("✅ Janela detectada! Rolando para carregar todos os nomes...")
            contador_posts += 1

            # Atualizamos os seletores internos para usarem a janela correta como base
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

                page.evaluate(f"""
                    var objDiv = document.querySelector("{seletor_scroll}");
                    if(objDiv) {{ objDiv.scrollTop = objDiv.scrollHeight; }}
                """)
                time.sleep(1.5)

            # --- EXTRAÇÃO E SOMA DE PONTOS ---
            elementos_nome = page.locator(seletor_nomes).all_inner_texts()
            
            novas_reacoes = 0
            for texto in elementos_nome:
                nome_limpo = texto.split('\n')[0].strip()
                if nome_limpo:
                    ranking_reacoes[nome_limpo] = ranking_reacoes.get(nome_limpo, 0) + 1
                    novas_reacoes += 1

            print(f"🎉 Pronto! {novas_reacoes} reações mapeadas neste post.")

            # Fecha a janela de reações
            page.keyboard.press("Escape")
            time.sleep(1)

        print("\n=========================================")
        print("COLETA FINALIZADA! Encerrando navegador e gerando relatório...")
        browser.close()

    # --- EXPORTAÇÃO PARA O CSV (FORA DO NAVEGADOR) ---
    dados_finais = [{"Nome": nome, "Total_Reacoes": qtd} for nome, qtd in ranking_reacoes.items()]
    
    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Total_Reacoes", ascending=False)
        df.to_csv(csv_file, index=False, encoding="utf-8-sig")
        print(f"✅ SUCESSO TOTAL! {len(dados_finais)} pessoas diferentes engajaram nas publicações que você selecionou.")
        print(f"📁 Ranking salvo no arquivo: {csv_file}")
    else:
        print("Nenhuma reação foi salva.")

if __name__ == "__main__":
    scrape_interativo()