import streamlit as st
import pandas as pd
import sqlite3
import requests
import time
import os
from datetime import datetime
import plotly.express as px

# --- BIBLIOTECAS DO ROBÔ ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="SAGE Analytics - 3ª GRE", layout="wide")
DB_PATH = 'quadro_aulas.db'
LOCK_FILE = 'sistema_ocupado.lock' # Arquivo que serve de sinal de "Ocupado"
URL_API_ALUNOS = "https://api.escola.see.pb.gov.br/api/Estudante/visao-gre-2025/"
# ANO_LETIVO_ID = "0c8c2de2-69f6-4858-9c6d-0319cf3413c9"
ANO_LETIVO_ID = "50018994-3fec-4ed7-baec-cc3b869ade81"

# ==============================================================================
# 1. FUNÇÕES DE BANCO DE DADOS (Com Timeout para evitar travamento)
# ==============================================================================

def get_db_connection():
    # timeout=30: Se o banco estiver ocupado, espera 30 segundos antes de dar erro
    return sqlite3.connect(DB_PATH, timeout=30) 

def inicializar_banco():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico_coletas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT, escola_nome TEXT, escola_id TEXT, qtd_alunos INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alunos_rede (
            matricula TEXT PRIMARY KEY, nome TEXT, turma TEXT, turno TEXT, 
            escola TEXT, escola_id TEXT, nascimento TEXT
        )
    """)
    conn.commit()
    conn.close()

def carregar_ids_escolas():
    conn = get_db_connection()
    try:
        query = "SELECT DISTINCT escola_id, escola_nome FROM professores_rede WHERE escola_id IS NOT NULL AND escola_id != ''"
        df = pd.read_sql_query(query, conn)
        return df.values.tolist() 
    except: return []
    finally: conn.close()

def salvar_lote_alunos(lista_alunos, escola_nome, escola_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for aluno in lista_alunos:
            val_id = str(aluno.get('matricula') or aluno.get('id') or '')
            val_nome = aluno.get('nome') or ''
            val_turma = aluno.get('turmaNome') or aluno.get('turma') or ''
            val_turno = aluno.get('turnoNome') or aluno.get('turno') or ''
            val_nasc = aluno.get('dataNascimento') or ''
            
            cursor.execute("""
                INSERT OR REPLACE INTO alunos_rede 
                (matricula, nome, turma, turno, escola, escola_id, nascimento)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (val_id, val_nome, val_turma, val_turno, escola_nome, escola_id, val_nasc))
        conn.commit()
    except Exception as e:
        st.error(f"Erro ao salvar lote: {e}")
    finally:
        conn.close()

def registrar_historico_escola(escola_nome, escola_id, total_alunos):
    conn = get_db_connection()
    try:
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO historico_coletas (data_hora, escola_nome, escola_id, qtd_alunos)
            VALUES (?, ?, ?, ?)
        """, (agora, escola_nome, escola_id, total_alunos))
        conn.commit()
    finally:
        conn.close()

# ==============================================================================
# 2. FUNÇÕES DO ROBÔ
# ==============================================================================

def login_selenium(cpf, senha):
    options = webdriver.ChromeOptions()
    # Configurações OBRIGATÓRIAS para rodar em servidor (Linux/Streamlit Cloud)
    options.add_argument("--headless")  # Não abre janela
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    
    try:
        # Tenta usar a instalação padrão do Linux (Streamlit Cloud)
        service = Service() 
        
        # Se estiver no Windows (seu PC), usa o instalador automático
        if os.name == 'nt': 
            service = Service(ChromeDriverManager().install())
            
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.get("https://escola.see.pb.gov.br")
        wait = WebDriverWait(driver, 20)

        wait.until(EC.presence_of_element_located((By.NAME, "cpf"))).send_keys(cpf)
        driver.find_element(By.XPATH, "//input[@type='password']").send_keys(senha)
        driver.find_element(By.TAG_NAME, "button").click()

        time.sleep(8) 
        token = driver.execute_script("return window.localStorage.getItem('seectpb.token');")
        
        driver.quit() # Fecha o navegador para economizar memória do servidor
        
        if token:
            token = token.replace('"', '').replace("'", "")
            # Cookies não são estritamente necessários se temos o Bearer Token, 
            # mas se precisar, pegue antes do quit.
            return token, [] 
        return None, None
    except Exception as e:
        st.error(f"Erro no Selenium: {e}")
        return None, None
# def login_selenium(cpf, senha):
#     options = webdriver.ChromeOptions()
#     options.add_argument("--headless")
#     options.add_argument("--no-sandbox")
#     options.add_argument("--disable-dev-shm-usage")
    
#     try:
#         service = Service(ChromeDriverManager().install())
#         driver = webdriver.Chrome(service=service, options=options)
#         driver.get("https://escola.see.pb.gov.br")
#         wait = WebDriverWait(driver, 20)

#         try:
#             wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/app-root/app-layout-no-auth/app-login/div/div/div[1]/form/div[3]/div/div/div/input'))).send_keys(cpf)
#         except:
#             driver.find_element(By.XPATH, '/html/body/app-root/app-layout-no-auth/app-login/div/div/div[1]/form/div[3]/div/div/div/input').send_keys(cpf)
            
#         try:
#             wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/app-root/app-layout-no-auth/app-login/div/div/div[1]/form/div[4]/div/div[1]/div/input'))).send_keys(senha)
#         except:
#             driver.find_element(By.XPATH, '/html/body/app-root/app-layout-no-auth/app-login/div/div/div[1]/form/div[4]/div/div[1]/div/input').send_keys(senha)

#         wait.until(EC.element_to_be_clickable((By.XPATH, '/html/body/app-root/app-layout-no-auth/app-login/div/div/div[1]/form/div[5]/div/button'))).click()

#         time.sleep(8) 
#         token = driver.execute_script("return window.localStorage.getItem('seectpb.token');")
        
#         if token:
#             token = token.replace('"', '').replace("'", "")
#             cookies = driver.get_cookies()
#             driver.quit()
#             return token, cookies
#         driver.quit()
#         return None, None
#     except: return None, None

def executar_varredura(token, cookies, lista_escolas, progress_bar, status_text):
    session = requests.Session()
    for c in cookies: session.cookies.set(c['name'], c['value'])
    session.headers.update({'Authorization': f'Bearer {token}'})

    total_escolas = len(lista_escolas)
    
    # Limpa tabela atual (Use com cuidado em multiusuário, mas ok com o LOCK)
    conn = get_db_connection()
    conn.execute("DELETE FROM alunos_rede") 
    conn.commit()
    conn.close()

    for i, (esc_id, esc_nome) in enumerate(lista_escolas):
        pct = (i + 1) / total_escolas
        progress_bar.progress(pct)
        status_text.markdown(f"**Processando [{i+1}/{total_escolas}]:** {esc_nome}")
        
        pagina = 1
        total_alunos_escola = 0
        erros = 0
        while True:
            try:
                params = {'page': pagina, 'pageSize': 100, 'anoLetivoId': ANO_LETIVO_ID, 'escolaId': esc_id}
                resp = session.get(URL_API_ALUNOS, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    lista = []
                    if 'data' in data:
                        if isinstance(data['data'], list): lista = data['data']
                        elif isinstance(data['data'], dict): lista = data['data'].get('data', [])
                    if not lista: break
                    salvar_lote_alunos(lista, esc_nome, esc_id)
                    total_alunos_escola += len(lista)
                    pagina += 1
                    erros = 0
                else:
                    erros += 1
                    time.sleep(1)
                    if erros > 3: break
            except:
                erros += 1
                if erros > 3: break
        
        registrar_historico_escola(esc_nome, esc_id, total_alunos_escola)

# ==============================================================================
# 3. INTERFACE DO DASHBOARD
# ==============================================================================

inicializar_banco()

st.sidebar.title("🎮 Controle do Robô")

# --- CARREGA ESCOLAS ---
escolas_db = carregar_ids_escolas()
# FILTRO DE EXCLUSÃO DA ESCOLA INTRUSA
escolas_db = [e for e in escolas_db if e[1] != "EEEF MANUEL BARBOSA DE LUCENA"]

if not escolas_db:
    st.sidebar.error("⚠️ Sem tabela de professores. Rode o robô de professores primeiro.")
else:
    st.sidebar.success(f"✅ {len(escolas_db)} escolas na base.")

st.sidebar.divider()

# --- LÓGICA DO SEMÁFORO (LOCK) ---
if os.path.exists(LOCK_FILE):
    st.sidebar.warning("⚠️ Uma atualização está em andamento por outro usuário. Aguarde finalizar.")
    if st.sidebar.button("Forçar Desbloqueio (Use com Cuidado)"):
        try:
            os.remove(LOCK_FILE)
            st.rerun()
        except: pass
else:
    # --- AQUI ESTÁ A MÁGICA: clear_on_submit=True ---
    # Isso limpa os campos CPF e SENHA assim que o botão é clicado
    with st.sidebar.form("form_login", clear_on_submit=True):
        st.write("Login SAGE")
        cpf = st.text_input("CPF")
        senha = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("🔄 RODAR ATUALIZAÇÃO")

    if submitted:
        if not cpf or not senha:
            st.sidebar.warning("Preencha login.")
        elif not escolas_db:
            st.sidebar.warning("Sem escolas.")
        else:
            # CRIA O ARQUIVO DE LOCK
            with open(LOCK_FILE, 'w') as f:
                f.write("ocupado")
            
            try:
                status = st.empty()
                bar = st.progress(0)
                status.info("🔑 Logando e Iniciando...")
                
                # O robô recebe os dados antes deles serem limpos da memória
                token, cookies = login_selenium(cpf, senha)
                
                if token:
                    status.info("🚀 Atualizando dados... Isso pode levar alguns minutos.")
                    executar_varredura(token, cookies, escolas_db, bar, status)
                    status.success("Atualizado com Sucesso!")
                    time.sleep(2)
                else:
                    status.error("❌ Erro no login ou senha incorreta.")
                    # Como limpou os campos, o usuário terá que digitar de novo (segurança)
            except Exception as e:
                st.error(f"Erro crítico: {e}")
            finally:
                # REMOVE O LOCK NO FINAL
                if os.path.exists(LOCK_FILE):
                    os.remove(LOCK_FILE)
                st.rerun()
# st.sidebar.title("🎮 Controle do Robô")

# # --- CARREGA ESCOLAS ---
# escolas_db = carregar_ids_escolas()
# # FILTRO DE EXCLUSÃO DA ESCOLA INTRUSA
# escolas_db = [e for e in escolas_db if e[1] != "EEEF MANUEL BARBOSA DE LUCENA"]

# if not escolas_db:
#     st.sidebar.error("⚠️ Sem tabela de professores. Rode o robô de professores primeiro.")
# else:
#     st.sidebar.success(f"✅ {len(escolas_db)} escolas na base.")

# st.sidebar.divider()

# # --- LÓGICA DO SEMÁFORO (LOCK) ---
# # Verifica se já existe uma atualização rodando
# if os.path.exists(LOCK_FILE):
#     st.sidebar.warning("⚠️ Uma atualização está em andamento por outro usuário. Aguarde finalizar.")
#     # Mostra um botão de "Forçar Desbloqueio" caso trave (opcional, mas útil)
#     if st.sidebar.button("Forçar Desbloqueio (Use com Cuidado)"):
#         try:
#             os.remove(LOCK_FILE)
#             st.rerun()
#         except:
#             pass
# else:
#     # Se não estiver bloqueado, mostra o formulário de login
#     with st.sidebar.form("form_login"):
#         st.write("Login SAGE")
#         cpf = st.text_input("CPF")
#         senha = st.text_input("Senha", type="password")
#         submitted = st.form_submit_button("🔄 RODAR ATUALIZAÇÃO")

#     if submitted:
#         if not cpf or not senha:
#             st.sidebar.warning("Preencha login.")
#         elif not escolas_db:
#             st.sidebar.warning("Sem escolas.")
#         else:
#             # CRIA O ARQUIVO DE LOCK
#             with open(LOCK_FILE, 'w') as f:
#                 f.write("ocupado")
            
#             try:
#                 status = st.empty()
#                 bar = st.progress(0)
#                 status.info("🔑 Logando e Iniciando...")
                
#                 token, cookies = login_selenium(cpf, senha)
                
#                 if token:
#                     status.info("🚀 Atualizando dados... Isso pode levar alguns minutos.")
#                     executar_varredura(token, cookies, escolas_db, bar, status)
#                     status.success("Atualizado com Sucesso!")
#                     time.sleep(2)
#                 else:
#                     status.error("❌ Erro no login.")
#             except Exception as e:
#                 st.error(f"Erro crítico: {e}")
#             finally:
#                 # REMOVE O LOCK NO FINAL (MESMO SE DER ERRO)
#                 if os.path.exists(LOCK_FILE):
#                     os.remove(LOCK_FILE)
#                 st.rerun()

st.sidebar.divider()
st.sidebar.info("Agendamentos Automáticos: 11:30 e 16:30")

# --- DADOS E VISUALIZAÇÃO ---
conn = get_db_connection()
try:
    df_atual = pd.read_sql_query("SELECT escola, COUNT(*) as total FROM alunos_rede GROUP BY escola HAVING total > 0 ORDER BY total DESC", conn)
    df_hist = pd.read_sql_query("SELECT * FROM historico_coletas ORDER BY data_hora ASC", conn)
    df_todas = pd.read_sql_query("SELECT DISTINCT escola_nome FROM professores_rede", conn)
except:
    df_atual, df_hist, df_todas = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
conn.close()

# --- FILTRO DE EXCLUSÃO VISUAL ---
ESCOLA_PARA_REMOVER = "EEEF MANUEL BARBOSA DE LUCENA"
if not df_atual.empty: df_atual = df_atual[df_atual['escola'] != ESCOLA_PARA_REMOVER]
if not df_todas.empty: df_todas = df_todas[df_todas['escola_nome'] != ESCOLA_PARA_REMOVER]
if not df_hist.empty: df_hist = df_hist[df_hist['escola_nome'] != ESCOLA_PARA_REMOVER]

if df_atual.empty:
    st.warning("Banco vazio. Use o menu lateral para atualizar.")
    st.stop()

# --- ZERADAS ---
try:
    set_todas = set(df_todas['escola_nome'].dropna().str.strip())
    set_com_alunos = set(df_atual['escola'].unique())
    lista_zeradas = sorted(list(set_todas - set_com_alunos))
except:
    lista_zeradas = []

total_rede = df_atual['total'].sum()
top_escola = df_atual.iloc[0]

st.title("📊 Monitoramento de Matrículas - 3ª GRE")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Alunos", f"{total_rede:,.0f}".replace(",", "."))
c2.metric("Escolas Ativas", len(df_atual))
c3.metric("Escolas ZERADAS", len(lista_zeradas), delta_color="inverse")
c4.metric("Maior Escola", top_escola['escola'], f"{top_escola['total']}")

st.divider()

lista_alfabetica = sorted(df_atual['escola'].unique())
try: idx = lista_alfabetica.index(top_escola['escola'])
except: idx = 0
escola_sel = st.selectbox("🏫 Selecione a Escola (A-Z):", lista_alfabetica, index=idx)

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader(f"📈 Evolução: {escola_sel}")
    if not df_hist.empty:
        d_esc = df_hist[df_hist['escola_nome'] == escola_sel].copy()
        if not d_esc.empty:
            d_esc['data_hora'] = pd.to_datetime(d_esc['data_hora'])
            vh = df_atual[df_atual['escola'] == escola_sel]['total'].values[0]
            fig = px.line(d_esc, x='data_hora', y='qtd_alunos', markers=True, 
                          title=f"Hoje: {vh} alunos", labels={'qtd_alunos':''})
            fig.update_traces(line_color='#1f77b4', line_width=3)
            st.plotly_chart(fig, use_container_width=True)
        else: st.info("Sem histórico.")
    
    st.divider()
    st.subheader("🚨 Escolas Zeradas (Ligar Urgente)")
    if lista_zeradas:
        df_z = pd.DataFrame(lista_zeradas, columns=["Nome da Escola"])
        st.dataframe(df_z, use_container_width=True, height=400, hide_index=True)
    else:
        st.success("🎉 Nenhuma escola zerada!")

with col2:
    st.subheader("🏆 Ranking (Maior para Menor)")
    df_rank = df_atual.sort_values(by='total', ascending=True)
    h = max(600, len(df_rank) * 30)
    fig = px.bar(df_rank, x='total', y='escola', orientation='h', text='total', height=h)
    fig.update_traces(textposition='outside', marker_color='#2ca02c', cliponaxis=False)
    fig.update_layout(yaxis={'categoryorder':'total ascending'}, margin=dict(t=10,b=10))
    st.plotly_chart(fig, use_container_width=True)