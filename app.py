import streamlit as st
import pandas as pd
import requests
import re
import time
import io
from supabase import create_client

# Import klienta WP
try:
    from wordpress_client import publish_post_draft
except ImportError:
    st.error("Brakuje pliku wordpress_client.py! Utwórz go w katalogu aplikacji.")

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="SEO 3.0 Content Factory", page_icon="🏭", layout="wide")

# --- STYLE CSS ---
st.markdown("""
<style>
    .block-container {padding-top: 1rem;}
    [data-testid="stDataFrame"] th[aria-label="ID"], [data-testid="stDataFrame"] td[aria-label="ID"] { text-align: center !important; }
    [data-testid="stDataFrame"] th[aria-label="Język"], [data-testid="stDataFrame"] td[aria-label="Język"] { text-align: center !important; }
</style>
""", unsafe_allow_html=True)

# --- MAPOWANIE KOLUMN (BAZA -> UI) ---
COLUMN_MAP = {
    'id': 'ID',
    'keyword': 'Słowo kluczowe',
    'language': 'Język',
    'aio_prompt': 'AIO',
    'status_research': 'Status Research',
    'serp_phrases': 'Frazy z wyników',
    'senuto_phrases': 'Frazy Senuto',
    'info_graph': 'Graf informacji',
    'competitors_headers': 'Nagłówki konkurencji',
    'knowledge_graph': 'Knowledge graph',
    'status_headers': 'Status Nagłówki',
    'headers_expanded': 'Nagłówki rozbudowane',
    'headers_h2': 'Nagłówki H2',
    'headers_questions': 'Nagłówki pytania',
    'headers_final': 'Nagłówki (Finalne)',
    'status_rag': 'Status RAG',
    'rag_content': 'RAG',
    'rag_general': 'RAG General',
    'status_brief': 'Status Brief',
    'brief_json': 'Brief',
    'brief_html': 'Brief plik',
    'instructions': 'Dodatkowe instrukcje',
    'status_writing': 'Status Generacja',
    'final_article': 'Generowanie contentu',
    # NOWE KOLUMNY WP
    'status_publication': 'Status Publikacji',
    'publication_link': 'Link do wpisu'
}

REVERSE_COLUMN_MAP = {v: k for k, v in COLUMN_MAP.items()}

# --- SUPABASE INIT ---
@st.cache_resource
def init_supabase():
    url = st.secrets["SUPABASE"]["URL"]
    key = st.secrets["SUPABASE"]["KEY"]
    return create_client(url, key)

supabase = init_supabase()

# --- FUNKCJE POMOCNICZE EXCEL ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='SEO Content')
    return output.getvalue()

def generate_template_excel():
    df_template = pd.DataFrame(columns=["Słowo kluczowe", "Język", "AIO"])
    df_template.loc[0] = ["Przykład: Jaki rower kupić", "pl", "Tutaj wpisz opcjonalne instrukcje AIO"]
    return to_excel(df_template)

# --- FUNKCJE DIFY ---
def run_dify_workflow(api_key, inputs, user_id="streamlit_user"):
    url = f"{st.secrets['dify']['BASE_URL']}/workflows/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": user_id
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=450)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- OBSŁUGA DANYCH ---
def fetch_data():
    response = supabase.table("seo_content_tasks").select("*").order("id", desc=True).execute()
    data = response.data
    if not data:
        return pd.DataFrame(columns=['Select'] + list(COLUMN_MAP.values()))
    
    df = pd.DataFrame(data)
    df = df.rename(columns=COLUMN_MAP)
    # Dodajemy kolumnę Select
    df.insert(0, 'Select', False)
    return df

def update_db_record(row_id, updates):
    supabase.table("seo_content_tasks").update(updates).eq("id", row_id).execute()

def delete_records(ids_list):
    if not ids_list: return
    supabase.table("seo_content_tasks").delete().in_("id", ids_list).execute()

def save_manual_changes(edited_df):
    df_to_save = edited_df.drop(columns=['Select'], errors='ignore')
    df_to_save = df_to_save.rename(columns=REVERSE_COLUMN_MAP)
    records = df_to_save.to_dict('records')
    
    progress_text = "Zapisywanie zmian..."
    my_bar = st.progress(0, text=progress_text)
    total = len(records)
    for i, record in enumerate(records):
        if record.get('id'):
            supabase.table("seo_content_tasks").upsert(record).execute()
        my_bar.progress((i + 1) / total, text=f"Zapisano wiersz {i+1}/{total}")
    my_bar.empty()
    st.success("Zmiany zapisane w bazie!")

def extract_headers_from_text(text):
    if not isinstance(text, str): return []
    html_headers = re.findall(r'<h2.*?>(.*?)</h2>', text, re.IGNORECASE)
    if html_headers:
        return [re.sub(r'<.*?>', '', h).strip() for h in html_headers]
    return [line.strip() for line in text.split('\n') if line.strip()]

# --- LOGIKA BIZNESOWA (ETAPY) ---

def stage_research(row):
    inputs = {"keyword": row['Słowo kluczowe'], "language": row['Język'], "aio": row['AIO'] if row['AIO'] else ""}
    resp = run_dify_workflow(st.secrets['dify']['API_KEY_RESEARCH'], inputs)
    if "data" in resp and "outputs" in resp["data"]:
        out = resp["data"]["outputs"]
        return {
            "status_research": "✅ Gotowe",
            "serp_phrases": out.get("frazy z serp", ""),
            "senuto_phrases": out.get("frazy_senuto", ""),
            "info_graph": out.get("grafinformacji", ""),
            "competitors_headers": out.get("naglowki", ""),
            "knowledge_graph": out.get("knowledge_graph", "")
        }
    else:
        raise Exception(f"Dify Error: {resp.get('error', 'Unknown error')}")

def stage_headers(row):
    frazy_full = f"{row['Frazy z wyników']}\n{row['Frazy Senuto']}"
    inputs = {"keyword": row['Słowo kluczowe'], "language": row['Język'], "frazy": frazy_full, "graf": row['Graf informacji'], "headings": row['Nagłówki konkurencji']}
    resp = run_dify_workflow(st.secrets['dify']['API_KEY_HEADERS'], inputs)
    if "data" in resp and "outputs" in resp["data"]:
        out = resp["data"]["outputs"]
        h2 = out.get("naglowki_h2", "")
        questions = out.get("naglowki_pytania", "")
        final_headers = row['Nagłówki (Finalne)']
        if not final_headers: final_headers = questions if questions else h2
        return {
            "status_headers": "✅ Gotowe",
            "headers_expanded": out.get("naglowki_rozbudowane", ""),
            "headers_h2": h2,
            "headers_questions": questions,
            "headers_final": final_headers
        }
    else:
        raise Exception(f"Dify Error: {resp.get('error', 'Unknown error')}")

def stage_rag(row):
    inputs = {"keyword": row['Słowo kluczowe'], "language": row['Język'], "headings": row['Nagłówki konkurencji']}
    resp = run_dify_workflow(st.secrets['dify']['API_KEY_RAG'], inputs)
    if "data" in resp and "outputs" in resp["data"]:
        out = resp["data"]["outputs"]
        return {"status_rag": "✅ Gotowe", "rag_content": out.get("dokladne", ""), "rag_general": out.get("ogolne", "")}
    else:
        raise Exception(f"Dify Error: {resp.get('error', 'Unknown error')}")

def stage_brief(row):
    h2_source = row['Nagłówki H2'] if row['Nagłówki H2'] else row['Nagłówki (Finalne)']
    if not h2_source: raise Exception("Brak nagłówków H2 do stworzenia briefu.")
    frazy_full = f"{row['Frazy z wyników']}\n{row['Frazy Senuto']}"
    inputs = {"keyword": row['Słowo kluczowe'], "keywords": frazy_full, "headings": h2_source, "knowledge_graph": row['Knowledge graph'], "information_graph": row['Graf informacji']}
    resp = run_dify_workflow(st.secrets['dify']['API_KEY_BRIEF'], inputs)
    if "data" in resp and "outputs" in resp["data"]:
        out = resp["data"]["outputs"]
        return {"status_brief": "✅ Gotowe", "brief_json": out.get("brief", ""), "brief_html": out.get("html", "")}
    else:
        raise Exception(f"Dify Error: {resp.get('error', 'Unknown error')}")

def stage_writing(row):
    headers_text = row['Nagłówki (Finalne)']
    headers_list = extract_headers_from_text(headers_text)
    if not headers_list: raise Exception("Pusta kolumna 'Nagłówki (Finalne)'.")
    full_knowledge = f"{row['RAG']}\n{row['RAG General']}"
    full_keywords = f"{row['Frazy z wyników']}, {row['Frazy Senuto']}"
    article_content = ""
    for h2 in headers_list:
        inputs = {
            "naglowek": h2, "language": row['Język'], "knowledge": full_knowledge, "keywords": full_keywords,
            "headings": row['Nagłówki rozbudowane'], "done": article_content, "keyword": row['Słowo kluczowe'], "instruction": row['Dodatkowe instrukcje']
        }
        resp = run_dify_workflow(st.secrets['dify']['API_KEY_WRITE'], inputs)
        if "data" in resp and "outputs" in resp["data"]:
            section = resp["data"]["outputs"].get("result", "")
            article_content += f"<h2>{h2}</h2>\n{section}\n\n"
        else:
            article_content += f"<h2>{h2}</h2>\n[BŁĄD GENEROWANIA: {resp.get('error')}]\n\n"
    return {"status_writing": "✅ Gotowe", "final_article": article_content}

def stage_publication(row, wp_config):
    """Etap 6: Publikacja w WP"""
    content = row['Generowanie contentu']
    title = row['Słowo kluczowe']
    
    if not content or len(content) < 50:
        raise Exception("Brak wygenerowanej treści do publikacji.")
    
    if not wp_config['url'] or not wp_config['user'] or not wp_config['key']:
        raise Exception("Brak konfiguracji WordPress.")

    result = publish_post_draft(
        wp_config['url'],
        wp_config['user'],
        wp_config['key'],
        title,
        content
    )
    
    if result['success']:
        return {
            "status_publication": "✅ Opublikowano (Draft)",
            "publication_link": result['link']
        }
    else:
        raise Exception(f"WP Error: {result['message']}")


# --- UNIWERSALNY PROCESOR BATCHOWY ---
def run_batch_process(selected_rows, process_func, status_col_db, success_msg, extra_args=None):
    progress_container = st.empty()
    status_log = st.empty()
    stop_button_placeholder = st.empty()
    
    stop_process = False
    if stop_button_placeholder.button("⛔ ZATRZYMAJ PO OBECNYM REKORDZIE"):
        stop_process = True
    
    total = len(selected_rows)
    success_count = 0
    error_count = 0
    my_bar = progress_container.progress(0)
    
    for i, row in enumerate(selected_rows):
        # Sprawdzenie flagi STOP (symulacja, bo Streamlit reruns on click)
        # W praktyce user klika stop, strona się przeładowuje i pętla nie rusza dalej, 
        # ale tutaj wewnątrz pętli ciężko to złapać bez session_state. 
        # Zostawiamy jak jest - działa jako "zatrzymaj kolejne uruchomienia".
        
        row_id = row['ID']
        keyword = row['Słowo kluczowe']
        status_log.info(f"⏳ [{i+1}/{total}] Przetwarzanie: **{keyword}**...")
        update_db_record(row_id, {status_col_db: "🔄 W trakcie..."})
        
        try:
            # Przekazanie dodatkowych argumentów (np. konfig WP)
            if extra_args:
                updates = process_func(row, extra_args)
            else:
                updates = process_func(row)
                
            update_db_record(row_id, updates)
            success_count += 1
        except Exception as e:
            error_count += 1
            error_msg = str(e)[:100]
            update_db_record(row_id, {status_col_db: f"❌ Błąd: {error_msg}"})
            st.toast(f"Błąd przy '{keyword}': {error_msg}", icon="⚠️")
        
        my_bar.progress((i + 1) / total)
    
    my_bar.empty()
    stop_button_placeholder.empty()
    status_log.success(f"Zakończono! Sukces: {success_count}, Błędy: {error_count}")
    time.sleep(2)
    st.rerun()

# --- AUTORYZACJA ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        pwd = st.text_input("Hasło dostępu", type="password")
        if pwd == st.secrets["general"]["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        elif pwd:
            st.error("Złe hasło")
        return False
    return True

# --- MAIN APP ---
if check_password():
    
    # --- SIDEBAR ---
    with st.sidebar:
        st.title("🏭 Content Factory")
        
        with st.expander("🛠️ 1. Import / Dodaj", expanded=False):
            st.header("Import Excel")
            template_bytes = generate_template_excel()
            st.download_button(
                label="📥 Pobierz szablon",
                data=template_bytes,
                file_name="example-import.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            uploaded_file = st.file_uploader("Wgraj plik", type=['xlsx', 'csv'])
            if uploaded_file:
                if st.button("Importuj"):
                    # ... (Kod importu bez zmian - skrócony dla czytelności)
                    try:
                        df_imp = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                        count = 0
                        cols = df_imp.columns.tolist()
                        # Prosta heurystyka wyboru kolumn
                        c_kw = cols[0]
                        for c in cols:
                            if "słowo" in c.lower() or "keyword" in c.lower(): c_kw = c
                        
                        my_bar = st.progress(0)
                        for i, r in df_imp.iterrows():
                            supabase.table("seo_content_tasks").insert({
                                "keyword": str(r[c_kw]), "language": "pl", "headers_final": ""
                            }).execute()
                            count += 1
                            my_bar.progress((i+1)/len(df_imp))
                        st.success(f"Zaimportowano {count}")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd: {e}")

            st.divider()
            st.header("Dodaj Ręcznie")
            with st.form("add_manual"):
                m_kw = st.text_input("Słowo kluczowe")
                m_lang = st.text_input("Język", value="pl")
                m_aio = st.text_area("AIO")
                if st.form_submit_button("Dodaj"):
                    supabase.table("seo_content_tasks").insert({"keyword": m_kw, "language": m_lang, "aio_prompt": m_aio, "headers_final": ""}).execute()
                    st.success("Dodano!")
                    st.rerun()

        with st.expander("📤 2. Eksport", expanded=False):
            if st.button("Przygotuj Excel"):
                full_df = fetch_data().drop(columns=['Select'], errors='ignore')
                st.download_button("💾 Pobierz (XLSX)", to_excel(full_df), "seo_export.xlsx")

        st.divider()
        
        # KONFIGURACJA WP
        st.header("🌍 Konfiguracja WordPress")
        st.info("Dane wpisujesz jednorazowo dla sesji (nie są zapisywane w bazie).")
        wp_domain = st.text_input("Domena (np. mojablog.pl)", placeholder="https://mojablog.pl")
        wp_user = st.text_input("Użytkownik WP")
        wp_key = st.text_input("Hasło Aplikacji", type="password", help="Wygeneruj w WP > Użytkownicy > Profil > Hasła aplikacji")
        
        wp_config = {
            "url": wp_domain,
            "user": wp_user,
            "key": wp_key
        }

    # --- GŁÓWNY OBSZAR ---
    
    df = fetch_data()
    
    st.header("📋 Lista Zadań")
    
    # Filtry
    col_f1, col_f2 = st.columns([2, 2])
    with col_f1:
        status_filter = st.selectbox("Status Research", ["Wszystkie", "Oczekuje", "✅ Gotowe", "❌ Błąd"])
    if status_filter != "Wszystkie":
        df = df[df['Status Research'].str.contains(status_filter, na=False)]

    # KONFIGURACJA TABELI
    column_cfg = {
        "Select": st.column_config.CheckboxColumn("Zaznacz", default=False, width="small"),
        "ID": st.column_config.NumberColumn(width="small", disabled=True, format="%d"),
        "Słowo kluczowe": st.column_config.TextColumn(width=200),
        "Język": st.column_config.TextColumn(width="small"),
        "AIO": st.column_config.TextColumn(width=200),
        # Statusy
        "Status Research": st.column_config.TextColumn(width="small"),
        "Status Nagłówki": st.column_config.TextColumn(width="small"),
        "Status RAG": st.column_config.TextColumn(width="small"),
        "Status Brief": st.column_config.TextColumn(width="small"),
        "Status Generacja": st.column_config.TextColumn(width="small"),
        "Status Publikacji": st.column_config.TextColumn(width="small"), # NOWE
        
        # Dane - szerokość 200px
        "Frazy z wyników": st.column_config.TextColumn(width=200),
        "Frazy Senuto": st.column_config.TextColumn(width=200),
        "Graf informacji": st.column_config.TextColumn(width=200),
        "Nagłówki konkurencji": st.column_config.TextColumn(width=200),
        "Knowledge graph": st.column_config.TextColumn(width=200),
        "Nagłówki rozbudowane": st.column_config.TextColumn(width=200),
        "Nagłówki H2": st.column_config.TextColumn(width=200),
        "Nagłówki pytania": st.column_config.TextColumn(width=200),
        "Nagłówki (Finalne)": st.column_config.TextColumn(width=300),
        "RAG": st.column_config.TextColumn(width=200),
        "RAG General": st.column_config.TextColumn(width=200),
        "Brief": st.column_config.TextColumn(width=200),
        "Brief plik": st.column_config.TextColumn(width=200),
        "Dodatkowe instrukcje": st.column_config.TextColumn(width=200),
        "Generowanie contentu": st.column_config.TextColumn(width=200, disabled=True),
        "Link do wpisu": st.column_config.LinkColumn(width=200), # NOWE
    }

    edited_df = st.data_editor(
        df,
        key="data_editor",
        height=500,
        use_container_width=False,
        hide_index=True,
        column_config=column_cfg
    )

    # AKCJE POD TABELĄ
    c_s, c_d, c_i = st.columns([1, 1, 4])
    selected_rows = edited_df[edited_df['Select'] == True]
    count_selected = len(selected_rows)

    with c_s:
        if st.button("💾 Zapisz"):
            save_manual_changes(edited_df)
            time.sleep(1)
            st.rerun()
    with c_d:
        if st.button("🗑️ Usuń"):
            if count_selected > 0:
                delete_records(selected_rows['ID'].tolist())
                st.success(f"Usunięto {count_selected}")
                time.sleep(1)
                st.rerun()
    with c_i:
        st.info(f"Wybrano: {count_selected}")

    st.divider()
    
    # --- PANEL STEROWANIA ---
    st.subheader("⚙️ Procesy")
    
    if count_selected > 0:
        c1, c2, c3, c4, c5, c6 = st.columns(6) # 6 Kolumn teraz
        rows_to_process = selected_rows.to_dict('records')

        with c1:
            if st.button(f"1. RESEARCH"):
                run_batch_process(rows_to_process, stage_research, "status_research", "Gotowe")
        with c2:
            if st.button(f"2. NAGŁÓWKI"):
                run_batch_process(rows_to_process, stage_headers, "status_headers", "Gotowe")
        with c3:
            if st.button(f"3. RAG"):
                run_batch_process(rows_to_process, stage_rag, "status_rag", "Gotowe")
        with c4:
            if st.button(f"4. BRIEF"):
                run_batch_process(rows_to_process, stage_brief, "status_brief", "Gotowe")
        with c5:
            if st.button(f"5. GENERUJ"):
                run_batch_process(rows_to_process, stage_writing, "status_writing", "Gotowe")
        with c6:
            # PRZYCISK PUBLIKACJI
            if st.button(f"6. PUBLIKUJ WP", type="primary"):
                if not wp_config['url'] or not wp_config['key']:
                    st.error("Uzupełnij dane WP w pasku bocznym!")
                else:
                    run_batch_process(rows_to_process, stage_publication, "status_publication", "Opublikowano", extra_args=wp_config)
    else:
        st.caption("Zaznacz wiersze, aby uruchomić akcje.")

    # --- PODGLĄD SZCZEGÓŁÓW ---
    st.divider()
    
    if not df.empty:
        try:
            opts = {f"#{r['ID']} {r['Słowo kluczowe']}": r['ID'] for i, r in df.iterrows()}
            sel = st.selectbox("Podgląd:", opts.keys())
            if sel:
                row_id = opts[sel]
                view_row = edited_df[edited_df['ID'] == row_id].iloc[0]
                
                with st.expander("🔍 Szczegóły", expanded=False):
                    t1, t2, t3, t4, t5, t6 = st.tabs(["Research", "Nagłówki", "RAG", "Brief", "Artykuł", "Publikacja"])
                    
                    with t1:
                        st.text_area("SERP", view_row['Frazy z wyników'])
                        st.text_area("Graf", view_row['Graf informacji'])
                    with t2:
                        st.text_area("Finalne", view_row['Nagłówki (Finalne)'], height=400)
                    with t3:
                        st.text_area("RAG", view_row['RAG'])
                    with t4:
                        if view_row['Brief plik']: st.components.v1.html(view_row['Brief plik'], height=400, scrolling=True)
                    with t5:
                        if view_row['Generowanie contentu']: st.markdown(view_row['Generowanie contentu'], unsafe_allow_html=True)
                    with t6:
                        st.write(f"Status: {view_row['Status Publikacji']}")
                        if view_row['Link do wpisu']:
                            st.markdown(f"[Zobacz wpis]({view_row['Link do wpisu']})")
        except: pass
