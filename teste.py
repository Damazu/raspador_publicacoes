from playwright.sync_api import sync_playwright
import pandas as pd
import time
from pathlib import Path

# --- CONFIGURAÇÕES GERAIS ---
URL = "https://www.linkedin.com/feed/"
CSV_FILE = "ranking_engajamento_modular.csv"
STORAGE_STATE = Path("linkedin_state.json")

def realizar_login(page, context, url_destino):
    """
    Verifica se o LinkedIn está bloqueando o acesso.
    Caso positivo, pausa a execução para o usuário logar manualmente e salva a sessão.
    """
    precisa_logar = False
    
    # Verifica indícios de bloqueio (authwall, signup, botão de login)
    if "signup" in page.url or "authwall" in page.url or "login" in page.url:
        precisa_logar = True
    elif page.locator('a[href*="/login"], button:has-text("Entrar"), button:has-text("Sign in")').first.is_visible(timeout=3000):
        precisa_logar = True

    if precisa_logar:
        print("\n[!] O LinkedIn está pedindo login. Indo para a tela de acesso...")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        
        print("\n" + "="*60)
        print("⏰ O SCRIPT ESTÁ PAUSADO PARA VOCÊ FAZER O LOGIN!")
        print("1. Vá até a janela do Chrome que o robô abriu.")
        print("2. Faça seu login normalmente.")
        input("👉 QUANDO O FEED CARREGAR, APERTE 'ENTER' AQUI NO TERMINAL: ")
        print("="*60 + "\n")
        
        time.sleep(5) # Aguarda o redirecionamento automático do feed
        
        print("Indo para a página da empresa...")
        try:
            page.goto(url_destino, wait_until="domcontentloaded")
        except Exception:
            time.sleep(3)
            page.goto(url_destino, wait_until="domcontentloaded")
        time.sleep(4)

    # Salva o estado de login para as próximas execuções
    context.storage_state(path=str(STORAGE_STATE))


def extrair_reacoes(page, ranking_engajamento):
    """
    Controla a janela de curtidas: rola até o final, extrai os nomes e fecha.
    """
    base_modal_selector = "div[role='dialog'].social-details-reactors-modal"
    modal = page.locator(base_modal_selector).first
    
    if not modal.is_visible():
        print("❌ ERRO: A janela de curtidas não está aberta! Clique nas curtidas no navegador e tente de novo.")
        return False

    print("✅ Janela detectada! Rolando para carregar todas as reações...")
    
    seletor_scroll = f"{base_modal_selector} .artdeco-modal__content"
    seletor_nomes = f"{base_modal_selector} .artdeco-entity-lockup__title, {base_modal_selector} .artdeco-entity-title"

    pessoas_carregadas = 0
    tentativas_sem_novo_nome = 0
    
    # Scroll até carregar todos os nomes
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

    # Coleta os nomes e atualiza o Dicionário
    elementos_nome = page.locator(seletor_nomes).all_inner_texts()
    novas_reacoes = 0
    
    for texto in elementos_nome:
        nome_limpo = texto.split('\n')[0].strip()
        if nome_limpo:
            ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0})
            ranking_engajamento[nome_limpo]["reacoes"] += 1
            novas_reacoes += 1

    print(f"🎉 {novas_reacoes} reações mapeadas neste post.")
    
    # Fecha a janela de reações
    page.keyboard.press("Escape")
    time.sleep(1)
    
    return True


def extrair_comentarios(page, ranking_engajamento, comentarios_processados):
    """
    Clica no botão de carregar mais, extrai os autores dos comentários e ignora repetidos.
    """
    print("   🔎 Procurando botão 'Carregar mais comentários'...")
    
    # Clica no botão enquanto ele estiver visível na tela
    while True:
        btn_carregar = page.locator("button.comments-comments-list__load-more-comments-button:visible").first
        if btn_carregar.is_visible():
            try:
                btn_carregar.click(timeout=3000)
                print("   ⏳ Clicou em carregar mais... Aguardando...")
                time.sleep(2)
            except Exception:
                break
        else:
            break

    comentarios_html = page.locator(".comments-comment-item").all()
    novos_comentarios = 0
    
    for comentario in comentarios_html:
        urn = comentario.get_attribute("data-urn") or comentario.get_attribute("data-id")
        
        if not urn or urn in comentarios_processados:
            continue
        
        if comentario.is_visible():
            seletor_nome_comentario = ".comments-post-meta__name-text, .comments-post-meta__name, a[data-control-name='comment_actor']"
            nome_el = comentario.locator(seletor_nome_comentario).first
            
            if nome_el.is_visible():
                nome_limpo = nome_el.inner_text().split('\n')[0].strip()
                if nome_limpo:
                    ranking_engajamento.setdefault(nome_limpo, {"reacoes": 0, "comentarios": 0})
                    ranking_engajamento[nome_limpo]["comentarios"] += 1
                    comentarios_processados.add(urn)
                    novos_comentarios += 1
    
    print(f"   💬 {novos_comentarios} novos comentários mapeados!\n")


def salvar_relatorio(ranking_engajamento):
    """
    Consolida os dados do dicionário em um DataFrame Pandas e salva em CSV.
    """
    dados_finais = []
    for nome, dados in ranking_engajamento.items():
        total_engajamento = dados["reacoes"] + dados["comentarios"]
        dados_finais.append({
            "Nome": nome,
            "Qtd_Reacoes": dados["reacoes"],
            "Qtd_Comentarios": dados["comentarios"],
            "Engajamento_Total": total_engajamento
        })
    
    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df = df.sort_values(by="Engajamento_Total", ascending=False)
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
        print(f"✅ SUCESSO TOTAL! {len(dados_finais)} pessoas diferentes estão no ranking.")
        print(f"📁 Relatório completo salvo em: {CSV_FILE}")
    else:
        print("⚠️ Nenhum dado de engajamento foi coletado.")


def main():
    """
    Função principal que orquestra o fluxo do robô e o loop interativo.
    """
    ranking_engajamento = {}
    comentarios_processados = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        ctx_opts = {"locale": "pt-BR", "viewport": {"width": 1280, "height": 800}}
        
        if STORAGE_STATE.is_file():
            ctx_opts["storage_state"] = str(STORAGE_STATE)

        context = browser.new_context(**ctx_opts)
        page = context.new_page()

        print(f"Acessando: {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        time.sleep(4)

        # 1. Checa e faz login se necessário
        realizar_login(page, context, URL)

        print("\n" + "="*65)
        print("🤖 MODO SEMI-AUTOMÁTICO ATIVADO")
        print("👉 Deixe a janela de Reações aberta e aperte ENTER.")
        print("👉 Digite 'sair' a qualquer momento para gerar o Excel.")
        print("="*65 + "\n")

        contador_posts = 0

        # 2. Loop interativo (Humano <-> Robô)
        while True:
            comando = input(f"👉 [Post {contador_posts + 1}] Janela de REAÇÕES aberta? Aperte ENTER (ou 'sair'): ").strip().lower()

            if comando == 'sair':
                break

            # Extrai Reações
            sucesso_reacoes = extrair_reacoes(page, ranking_engajamento)
            
            if sucesso_reacoes:
                contador_posts += 1
                
                # Pergunta e extrai Comentários
                comando_coment = input(f"   💬 Quer extrair os COMENTÁRIOS agora? Deixe-os visíveis e aperte ENTER (ou 'n'): ").strip().lower()
                if comando_coment != 'n':
                    extrair_comentarios(page, ranking_engajamento, comentarios_processados)

        print("\n=========================================")
        print("COLETA FINALIZADA! Encerrando navegador...")
        browser.close()

    # 3. Salva a planilha final
    salvar_relatorio(ranking_engajamento)


if __name__ == "__main__":
    main()