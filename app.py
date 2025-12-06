# ==========================================
# APLIKASI: SN TRACKER PRO (V7.3 Layout Fix)
# ENGINE: Supabase (PostgreSQL)
# UPDATE: Memindahkan Danger Zone ke sebelah kanan
# menu Backup Database (Side-by-Side Layout)
# ==========================================

import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import time
import io
import re

# --- 1. SETUP HALAMAN ---
st.set_page_config(
    page_title="SN Tracker",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. KONEKSI SUPABASE ---
@st.cache_resource
def init_db():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"⚠️ Gagal koneksi Supabase: {e}")
        st.info("Pastikan Secrets [supabase] url dan key sudah disetting.")
        st.stop()

supabase = init_db()

# --- 3. STATE MANAGEMENT ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_role' not in st.session_state: st.session_state.user_role = ""
if 'keranjang' not in st.session_state: st.session_state.keranjang = []
if 'search_key' not in st.session_state: st.session_state.search_key = 0 
if 'confirm_logout' not in st.session_state: st.session_state.confirm_logout = False

# --- 4. CSS CUSTOMIZATION ---
st.markdown("""
    <style>
    /* VARIABEL DINAMIS */
    :root { 
        --brand-blue: #0095DA; 
        --brand-yellow: #F99D1C; 
        --card-bg: var(--secondary-background-color);
        --text-color: var(--text-color);
        --border-color: rgba(128, 128, 128, 0.2);
    }
    
    div.stButton > button[kind="primary"] {
        background: linear-gradient(90deg, #0095DA 0%, #007bb5 100%);
        border: none; color: white !important; font-weight: 700;
        padding: 10px 20px; border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        transition: all 0.3s ease;
    }
    div.stButton > button[kind="primary"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0, 149, 218, 0.3);
    }
    div.stButton > button[data-testid="baseButton-secondary"] {
        border: 1px solid #ff4b4b; color: #ff4b4b; border-radius: 8px;
    }
    div.stButton > button[data-testid="baseButton-secondary"]:hover {
        background-color: #ff4b4b; color: white; border-color: #ff4b4b;
    }

    .product-card-container {
        background-color: var(--card-bg); padding: 25px; border-radius: 12px;
        border: 1px solid var(--border-color); border-left: 6px solid var(--brand-blue);
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px; color: var(--text-color);
    }
    .product-title { font-size: 22px; font-weight: 700; margin-bottom: 5px; }
    .product-badge {
        background-color: rgba(0, 149, 218, 0.15); color: var(--brand-blue);
        padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; margin-right: 5px;
    }
    .product-stock {
        background-color: rgba(46, 125, 50, 0.15); color: #4caf50;
        padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 700;
    }
    .big-price-tag { font-size: 36px; font-weight: 800; color: var(--brand-yellow); margin-top: 15px; margin-bottom: 10px; }

    .metric-box {
        background-color: var(--card-bg); padding: 20px; border-radius: 12px;
        border: 1px solid var(--border-color); border-left: 4px solid var(--brand-blue);
        text-align: center; color: var(--text-color);
    }
    .metric-label { font-size: 14px; opacity: 0.7; font-weight: 600; text-transform: uppercase; }
    .metric-value { font-size: 28px; font-weight: 800; margin-top: 5px; }

    .info-card {
        padding: 20px; background-color: var(--card-bg); border: 1px solid var(--border-color);
        border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); margin-bottom: 20px;
    }
    .info-header {
        font-weight: 700; font-size: 16px; color: var(--brand-blue);
        margin-bottom: 15px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px;
    }

    .admin-card-blue {
        padding: 20px; border: 1px solid #0095DA; background-color: rgba(0, 149, 218, 0.05);
        border-radius: 10px; margin-bottom: 15px; color: var(--text-color);
        height: 100%; /* Agar tinggi sama */
    }
    .admin-card-red {
        padding: 20px; border: 1px solid #ff4b4b; background-color: rgba(255, 75, 75, 0.05);
        border-radius: 10px; margin-bottom: 15px; color: var(--text-color);
        height: 100%; /* Agar tinggi sama */
    }
    .admin-header { font-weight: 700; font-size: 18px; margin-bottom: 10px; display: flex; align-items: center; gap: 10px; }
    
    .stCode { font-family: 'Courier New', monospace; font-weight: bold; }
    div[data-testid="stExpander"] { border: 1px solid var(--border-color); background-color: var(--card-bg); border-radius: 8px; }
    
    .sidebar-alert {
        background-color: rgba(255, 75, 75, 0.1); 
        border: 1px solid #ff4b4b; 
        color: #ff4b4b; 
        padding: 12px; 
        border-radius: 8px; 
        font-size: 14px; 
        font-weight: 600;
        margin-top: 10px;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 5. FUNGSI LOGIC SUPABASE ---

def clear_cache():
    get_inventory_df.clear()
    get_history_df.clear()
    get_import_logs.clear()

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def format_rp(val): return f"Rp {val:,.0f}".replace(",", ".")

# --- READ DATA (Cached) ---
@st.cache_data(ttl=300)
def get_inventory_df():
    response = supabase.table('inventory').select("*").execute()
    data = response.data
    if not data: return pd.DataFrame(columns=['brand', 'sku', 'price', 'sn', 'status'])
    return pd.DataFrame(data)

@st.cache_data(ttl=300)
def get_history_df():
    response = supabase.table('transactions').select("*").order('timestamp', desc=True).execute()
    data = response.data
    if not data: return pd.DataFrame(columns=['trx_id', 'timestamp', 'user', 'total_bill'])
    return pd.DataFrame(data)

@st.cache_data(ttl=300)
def get_import_logs():
    response = supabase.table('import_logs').select("*").order('timestamp', desc=True).limit(20).execute()
    return response.data

# --- WRITE DATA ---

def log_import_activity(user, method, items_df):
    try:
        items_list = items_df[['brand', 'sku', 'sn', 'price']].to_dict('records')
        log_data = {'timestamp': datetime.now().isoformat(), 'user': user, 'method': method, 'total_items': len(items_df), 'items_detail': items_list}
        supabase.table('import_logs').insert(log_data).execute()
        clear_cache()
    except Exception as e: print(f"Log Error: {e}")

def add_stock_batch(user, brand, sku, price, sn_list):
    clean_sn_list = []
    for sn in sn_list:
        clean_sn = sn.strip().upper() 
        if clean_sn: clean_sn_list.append(clean_sn)
    clean_sn_list = list(set(clean_sn_list))
    if not clean_sn_list: return 0, 0, []

    try:
        response = supabase.table('inventory').select("sn").in_("sn", clean_sn_list).execute()
        existing_sns = [item['sn'] for item in response.data]
    except: existing_sns = []

    new_items = []
    log_items = []
    duplicate_items = []
    
    for sn in clean_sn_list:
        if sn in existing_sns: duplicate_items.append(sn)
        else:
            item = {'sn': sn, 'brand': brand, 'sku': sku, 'price': int(price), 'status': 'Ready', 'created_at': datetime.now().isoformat()}
            new_items.append(item); log_items.append(item)
    
    if new_items:
        try:
            supabase.table('inventory').insert(new_items).execute()
            log_import_activity(user, "Manual Input", pd.DataFrame(log_items))
            clear_cache()
        except Exception as e:
            st.error(f"Error Database: {e}")
            return 0, 0, []
    return len(new_items), len(duplicate_items), duplicate_items

def import_stock_from_df(user, df):
    df.columns = [c.lower().strip() for c in df.columns]
    df['sn'] = df['sn'].astype(str).str.strip().str.upper()
    df = df.drop_duplicates(subset=['sn'])
    sn_list_excel = df['sn'].tolist()
    existing_sns = []
    batch_size = 500
    for i in range(0, len(sn_list_excel), batch_size):
        batch = sn_list_excel[i:i+batch_size]
        res = supabase.table('inventory').select("sn").in_("sn", batch).execute()
        existing_sns.extend([x['sn'] for x in res.data])
    df_new = df[~df['sn'].isin(existing_sns)]
    df_dup = df[df['sn'].isin(existing_sns)]
    data_to_insert = []
    for index, row in df_new.iterrows():
        item = {'sn': row['sn'], 'brand': str(row['brand']), 'sku': str(row['sku']), 'price': int(row['price']), 'status': 'Ready', 'created_at': datetime.now().isoformat()}
        data_to_insert.append(item)
    if data_to_insert:
        try:
            for i in range(0, len(data_to_insert), 1000):
                batch = data_to_insert[i:i + 1000]
                supabase.table('inventory').insert(batch).execute()
            log_import_activity(user, "Excel Import", pd.DataFrame(data_to_insert))
            clear_cache()
            return True, len(data_to_insert), len(df_dup)
        except Exception as e: return False, str(e), 0
    return True, 0, len(df_dup)

def process_checkout(user, cart_items):
    total = sum(item['price'] for item in cart_items)
    sn_sold = [item['sn'] for item in cart_items]
    trx_id = f"TRX-{int(time.time())}"
    try:
        supabase.table('inventory').update({'status': 'Sold', 'sold_at': datetime.now().isoformat()}).in_('sn', sn_sold).execute()
        trx_data = {'trx_id': trx_id, 'timestamp': datetime.now().isoformat(), 'user': user, 'total_bill': total, 'items_count': len(sn_sold), 'item_details': cart_items}
        supabase.table('transactions').insert(trx_data).execute()
        clear_cache()
        return trx_id, total
    except Exception as e: st.error(f"Transaksi Gagal: {e}"); return None, 0

def update_stock_price(sn, new_price):
    supabase.table('inventory').update({'price': int(new_price)}).eq('sn', sn).execute(); clear_cache()

def delete_stock(sn):
    supabase.table('inventory').delete().eq('sn', sn).execute(); clear_cache()

def factory_reset(table_name):
    target_col = "sn" if table_name == "inventory" else "trx_id" if table_name == "transactions" else "id"
    try: supabase.table(table_name).delete().neq(target_col, 'dummy_val').execute()
    except Exception as e: st.error(f"Gagal reset {table_name}: {e}")
    clear_cache()

# --- FUNGSI HELPER EXCEL RAPI ---
def format_excel(writer, df, sheet_name):
    df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1, header=False)
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]
    header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top', 'fg_color': '#0095DA', 'font_color': '#FFFFFF', 'border': 1})
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)
        max_len = max(df[value].astype(str).apply(len).max() if not df.empty else 0, len(str(value))) + 2
        worksheet.set_column(col_num, col_num, max_len)

# --- 6. LOGIN ---
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align:center; color:#0095DA;'>SN <span style='color:#F99D1C;'>TRACKER</span></h1>", unsafe_allow_html=True)
            st.caption("v7.3 Admin Layout Fix", unsafe_allow_html=True)
            with st.form("lgn"):
                u = st.text_input("Username"); p = st.text_input("Password", type="password")
                if st.form_submit_button("LOGIN", use_container_width=True, type="primary"):
                    if u == "admin" and p == "admin123":
                        st.session_state.logged_in = True; st.session_state.user_role = "ADMIN"; st.rerun()
                    elif u == "kasir" and p == "blibli2025":
                        st.session_state.logged_in = True; st.session_state.user_role = "KASIR"; st.rerun()
                    else: st.error("Akses Ditolak")

if not st.session_state.logged_in: login_page(); st.stop()

# --- 7. SIDEBAR ---
df_master = get_inventory_df()

with st.sidebar:
    st.markdown("### 📦 SN Tracker")
    st.markdown(f"User: **{st.session_state.user_role}**")
    menu = st.radio("Menu Utama", ["🛒 Kasir", "📦 Gudang", "🔧 Admin Tools"] if st.session_state.user_role == "ADMIN" else ["🛒 Kasir", "📦 Gudang"], label_visibility="collapsed")
    st.divider()
    
    if st.button("🔄 Refresh Data"):
        clear_cache()
        st.toast("Data berhasil diperbarui!", icon="✅")
        time.sleep(0.5)
        st.rerun()
        
    if not df_master.empty:
        df_ready = df_master[df_master['status'] == 'Ready']
        if not df_ready.empty:
            stok_rekap = df_ready.groupby(['brand', 'sku']).size().reset_index(name='jumlah')
            stok_tipis = stok_rekap[stok_rekap['jumlah'] < 5]
            if not stok_tipis.empty:
                st.markdown(f"""<div class="sidebar-alert">⚠️ <b>{len(stok_tipis)} Barang Menipis!</b></div>""", unsafe_allow_html=True)

    st.markdown("<br>" * 3, unsafe_allow_html=True) 
    st.markdown("---")
    
    if st.session_state.confirm_logout:
        st.warning("Yakin ingin keluar?")
        c_yes, c_no = st.columns(2)
        if c_yes.button("✅ YA", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.keranjang = []
            st.session_state.confirm_logout = False
            st.rerun()
        if c_no.button("❌ BATAL", use_container_width=True):
            st.session_state.confirm_logout = False
            st.rerun()
    else:
        if st.button("🚪 KELUAR APLIKASI", use_container_width=True): 
            st.session_state.confirm_logout = True
            st.rerun()

# --- 8. KONTEN UTAMA ---

# === KASIR ===
if menu == "🛒 Kasir":
    st.title("🛒 Kasir")
    c_product, c_cart = st.columns([1.8, 1])
    with c_product:
        st.info("💡 Ketik Nama Barang / Scan Barcode")
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                df_ready['display'] = "[" + df_ready['brand'] + "] " + df_ready['sku'] + " (" + df_ready['price'].apply(format_rp) + ")"
                search_options = sorted(df_ready['display'].unique())
                pilih_barang = st.selectbox("Pilih Produk:", ["-- Pilih Produk --"] + search_options, key=f"sb_{st.session_state.search_key}", label_visibility="collapsed")
                if pilih_barang != "-- Pilih Produk --":
                    rows = df_ready[df_ready['display'] == pilih_barang]
                    if not rows.empty:
                        item = rows.iloc[0]; sku = item['sku']
                        sn_cart = [x['sn'] for x in st.session_state.keranjang]
                        avail = df_ready[(df_ready['sku'] == sku) & (~df_ready['sn'].isin(sn_cart))]
                        st.markdown(f"""<div class="product-card-container"><span class="product-badge">{item['brand']}</span><span class="product-stock">Stok Tersedia: {len(avail)}</span><div class="product-title">{sku}</div><div class="big-price-tag">{format_rp(item['price'])}</div></div>""", unsafe_allow_html=True)
                        col_sn, col_add = st.columns([2, 1])
                        with col_sn:
                            sn_list_sorted = sorted(avail['sn'].tolist(), key=natural_sort_key)
                            p_sn = st.multiselect("Pilih SN:", sn_list_sorted, placeholder="Pilih Nomor SN...", label_visibility="collapsed")
                        with col_add:
                            if st.button("TAMBAH ➕", type="primary", use_container_width=True):
                                if p_sn:
                                    for s in p_sn: st.session_state.keranjang.append(avail[avail['sn']==s].iloc[0].to_dict())
                                    st.session_state.search_key += 1; st.toast(f"{len(p_sn)} barang masuk keranjang!", icon="🛒"); time.sleep(0.1); st.rerun()
                                else: st.warning("Pilih SN dulu")
                    else: st.warning("Barang tidak ditemukan.")
            else: st.warning("Stok Gudang Kosong.")
        else: st.warning("Database Kosong.")

    with c_cart:
        st.markdown("### Keranjang")
        if st.session_state.keranjang:
            with st.container(height=450, border=True):
                st.caption("Klik tombol kecil di kanan SN untuk Copy.")
                for i, x in enumerate(st.session_state.keranjang):
                    st.markdown(f"**{x['sku']}**")
                    c_sn_code, c_price = st.columns([2.5, 1]) 
                    with c_sn_code: st.code(x['sn'], language="text") 
                    with c_price: st.markdown(f"<div style='text-align:right; margin-top: 5px; font-weight:bold;'>{format_rp(x['price'])}</div>", unsafe_allow_html=True)
                    st.divider()
            with st.container(border=True):
                tot = sum(item['price'] for item in st.session_state.keranjang)
                st.markdown(f"<div style='text-align:right'>Total Tagihan<br><span class='big-price'>{format_rp(tot)}</span></div>", unsafe_allow_html=True)
                if st.button("✅ BAYAR SEKARANG", type="primary", use_container_width=True):
                    tid, tbil = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                    if tid: st.session_state.keranjang = []; st.balloons(); st.toast("Transaksi Berhasil Disimpan!", icon="✅"); st.success("Transaksi Sukses!"); st.session_state.last_trx = {'id': tid, 'total': tbil}; st.rerun()
                if st.button("❌ Batal", use_container_width=True): st.session_state.keranjang = []; st.toast("Keranjang dibersihkan.", icon="🗑️"); st.rerun()
        else:
            with st.container(border=True):
                if 'last_trx' in st.session_state and st.session_state.last_trx:
                    st.success("✅ Transaksi Berhasil!")
                    st.write(f"ID: {st.session_state.last_trx['id']}")
                    st.write(f"Total: {format_rp(st.session_state.last_trx['total'])}")
                    if st.button("Tutup"): del st.session_state.last_trx; st.rerun()
                else: st.info("Keranjang Kosong")

# === GUDANG ===
elif menu == "📦 Gudang":
    st.title("📦 Manajemen Gudang")
    df_master = get_inventory_df() # Load data
    tabs = st.tabs(["📊 Dashboard Stok", "🔍 Cek Detail", "➕ Input Barang", "📜 Riwayat Import", "🛠️ Edit/Hapus"])
    
    with tabs[0]:
        st.subheader("Ringkasan Stok")
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                stok_rekap = df_ready.groupby(['brand', 'sku', 'price']).size().reset_index(name='Total Stok')
                stok_rekap = stok_rekap.sort_values(by=['brand', 'sku'])
                stok_tipis = stok_rekap[stok_rekap['Total Stok'] < 5]
                if not stok_tipis.empty:
                    st.error(f"⚠️ PERHATIAN: {len(stok_tipis)} Barang Stoknya Menipis (< 5 unit)")
                    with st.expander("Klik untuk Lihat Detail Barang Menipis", expanded=False):
                        st.dataframe(stok_tipis, use_container_width=True, column_config={"price": st.column_config.NumberColumn("Harga", format="Rp %d"), "Total Stok": st.column_config.ProgressColumn("Sisa Stok", format="%d", min_value=0, max_value=5, help="Segera restock!")}, hide_index=True)
                    st.markdown("---")
                c1, c2, c3 = st.columns(3)
                with c1: st.markdown(f"""<div class="metric-box"><div class="metric-label">TOTAL UNIT</div><div class="metric-value">{len(df_ready)}</div></div>""", unsafe_allow_html=True)
                with c2: st.markdown(f"""<div class="metric-box"><div class="metric-label">NILAI ASET</div><div class="metric-value">{format_rp(df_ready['price'].sum())}</div></div>""", unsafe_allow_html=True)
                with c3: st.markdown(f"""<div class="metric-box"><div class="metric-label">JENIS PRODUK</div><div class="metric-value">{len(stok_rekap)}</div></div>""", unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                max_stok = int(stok_rekap['Total Stok'].max())
                st.dataframe(stok_rekap, use_container_width=True, column_config={"price": st.column_config.NumberColumn("Harga", format="Rp %d"), "Total Stok": st.column_config.ProgressColumn("Stok", format="%d", min_value=0, max_value=max_stok)}, hide_index=True)
            else: st.info("Gudang Kosong.")
        else: st.info("Database Kosong.")

    with tabs[1]:
        st.markdown('<div class="info-card"><div class="info-header">🔍 Pencarian Detail SN</div>', unsafe_allow_html=True)
        if not df_master.empty:
            c_s1, c_s2 = st.columns(2)
            with c_s1: q = st.text_input("Cari SN/SKU:", placeholder="Ketik nomor SN...")
            with c_s2: fb = st.selectbox("Brand", ["All"] + sorted(df_master['brand'].unique().tolist()))
            dv = df_master.copy()
            is_filtered = False
            if q: 
                dv = dv[dv['sku'].str.contains(q, case=False) | dv['sn'].str.contains(q, case=False)]
                is_filtered = True
            if fb != "All": 
                dv = dv[dv['brand'] == fb]
                is_filtered = True
            col_config = {"price": st.column_config.NumberColumn("Harga", format="Rp %d"), "sn": "Serial Number", "sku": "Nama Barang"}
            if is_filtered:
                st.success(f"Ditemukan {len(dv)} barang.")
                st.dataframe(dv[['sn','sku','brand','price','status']], use_container_width=True, column_config=col_config, hide_index=True)
            else:
                with st.expander(f"📋 Tampilkan Semua Data ({len(dv)} Barang)", expanded=False):
                    st.dataframe(dv[['sn','sku','brand','price','status']], use_container_width=True, column_config=col_config, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[2]:
        if st.session_state.user_role == "ADMIN":
            st.markdown('<div class="info-card"><div class="info-header">➕ Input Stok Baru</div>', unsafe_allow_html=True)
            mode = st.radio("Metode:", ["Manual", "Upload Excel"], horizontal=True)
            st.divider()
            if mode == "Manual":
                with st.form("in", clear_on_submit=True):
                    c1,c2,c3 = st.columns(3); b=c1.text_input("Brand"); s=c2.text_input("SKU"); p=c3.number_input("Harga", step=5000)
                    sn = st.text_area("List SN (Enter pemisah):", help="Sistem otomatis ubah ke Huruf Besar & Tolak Duplikat.")
                    if st.form_submit_button("SIMPAN", type="primary"):
                        if b and s and sn: 
                            added, dups, dup_list = add_stock_batch(st.session_state.user_role, b, s, p, sn.strip().split('\n'))
                            if added > 0: st.toast(f"Berhasil input {added} item baru!", icon="✅"); st.success(f"✅ Berhasil input {added} item baru.")
                            if dups > 0: st.toast(f"Ada {dups} item duplikat ditolak.", icon="⚠️"); st.error(f"❌ Gagal {dups} item karena Duplikat."); st.write("List Duplikat:", dup_list)
                            time.sleep(2); st.rerun()
            else:
                template_df = pd.DataFrame([{'brand': 'SAMSUNG', 'sku': 'GALAXY A55 5G', 'price': 6000000, 'sn': 'SN1001'}])
                csv_buffer = template_df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download Template Excel/CSV", data=csv_buffer, file_name="template_stok.csv", mime="text/csv")
                uf = st.file_uploader("Upload File CSV/Excel", type=['xlsx','csv'])
                if uf and st.button("PROSES IMPORT", type="primary"):
                    df = pd.read_csv(uf) if uf.name.endswith('.csv') else pd.read_excel(uf)
                    ok, added, dups = import_stock_from_df(st.session_state.user_role, df)
                    if ok: st.toast(f"Import Selesai! (+{added})", icon="✅"); st.success(f"✅ Import Selesai! Berhasil: {added}, Duplikat: {dups}"); time.sleep(2); st.rerun()
                    else: st.error(added)
            st.markdown('</div>', unsafe_allow_html=True)
        else: st.warning("Khusus Admin")

    with tabs[3]:
        st.subheader("Log Import")
        if st.session_state.user_role == "ADMIN":
            logs = get_import_logs()
            if logs:
                for log in logs:
                    ts = pd.to_datetime(log['timestamp']).strftime("%d %b %Y %H:%M")
                    with st.expander(f"{ts} | {log['method']} | {log['total_items']} Item"):
                        st.dataframe(pd.DataFrame(log['items_detail']), use_container_width=True)
            else: st.info("Kosong")

    with tabs[4]:
        if st.session_state.user_role == "ADMIN":
            st.markdown('<div class="danger-card"><div class="danger-header">⚠️ Edit & Hapus Data</div>', unsafe_allow_html=True)
            if st.text_input("PIN Admin:", type="password") == "123456":
                src = st.text_input("Cari SN Edit:")
                if src and not df_master.empty:
                    de = df_master[df_master['sn'].str.contains(src, case=False)]
                    for i, r in de.iterrows():
                        with st.expander(f"{r['sku']} ({r['sn']})"):
                            np = st.number_input("Harga", value=int(r['price']), key=f"p{r['sn']}")
                            if st.button("Update", key=f"u{r['sn']}"): update_stock_price(r['sn'], np); st.toast("Harga berhasil diupdate!", icon="✅"); time.sleep(1); st.rerun()
                            if st.button("Hapus", key=f"d{r['sn']}", type="primary"): delete_stock(r['sn']); st.toast("Data berhasil dihapus!", icon="🗑️"); time.sleep(1); st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

# === ADMIN TOOLS ===
elif menu == "🔧 Admin Tools":
    if st.session_state.user_role == "ADMIN":
        st.title("🔧 Admin Tools")
        df_master = get_inventory_df() 
        tab1, tab2 = st.tabs(["📊 Ringkasan", "💾 Database"])
        
        with tab1:
            df_hist = get_history_df()
            if not df_hist.empty:
                m1, m2 = st.columns(2)
                m1.metric("Omzet Total", format_rp(df_hist['total_bill'].sum()))
                m2.metric("Total Transaksi", len(df_hist))
                st.divider()
                st.subheader("🕵️‍♀️ Cek Detail Transaksi")
                trx_options = df_hist['trx_id'].tolist()
                selected_trx = st.selectbox("Pilih ID Transaksi:", ["-- Pilih --"] + trx_options)
                if selected_trx != "-- Pilih --":
                    trx_data = df_hist[df_hist['trx_id'] == selected_trx].iloc[0]
                    c_info1, c_info2, c_info3 = st.columns(3)
                    ts_str = pd.to_datetime(trx_data['timestamp']).strftime("%d %b %Y, %H:%M")
                    c_info1.info(f"User: {trx_data['user']}")
                    c_info2.info(f"Waktu: {ts_str}")
                    c_info3.success(f"Total: {format_rp(trx_data['total_bill'])}")
                    if 'item_details' in trx_data and trx_data['item_details']:
                        items = trx_data['item_details']
                        if isinstance(items, list):
                            df_items = pd.DataFrame(items)
                            cols_wanted = ['sku', 'brand', 'sn', 'price']
                            cols_avail = [c for c in cols_wanted if c in df_items.columns]
                            st.write("##### 📋 Daftar Barang Terjual:")
                            st.dataframe(df_items[cols_avail], use_container_width=True, column_config={"price": st.column_config.NumberColumn("Harga", format="Rp %d")})
                        else: st.warning("Format detail item tidak dikenali.")
                    else: st.warning("Detail item tidak tersedia.")
                st.divider()
                st.subheader("Semua Riwayat")
                st.dataframe(df_hist[['trx_id', 'timestamp', 'user', 'total_bill']], use_container_width=True)
            else: st.info("Belum ada transaksi")

        with tab2:
            col_backup, col_danger = st.columns(2)
            with col_backup:
                st.markdown('<div class="admin-card-blue"><div class="admin-header">📥 Backup Data</div><p>Simpan data secara berkala ke Excel untuk arsip pribadi.</p>', unsafe_allow_html=True)
                if st.button("DOWNLOAD DATABASE LENGKAP (.xlsx)", use_container_width=True):
                    if not df_master.empty or not df_hist.empty:
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                            if not df_master.empty:
                                df_stok_clean = df_master.copy()
                                for col in df_stok_clean.columns:
                                    if pd.api.types.is_datetime64_any_dtype(df_stok_clean[col]):
                                        df_stok_clean[col] = df_stok_clean[col].astype(str)
                                format_excel(writer, df_stok_clean, 'Stok Gudang')
                            if not df_hist.empty:
                                df_hist_clean = df_hist.copy()
                                if 'timestamp' in df_hist_clean.columns:
                                    df_hist_clean['waktu_lokal'] = pd.to_datetime(df_hist_clean['timestamp']).dt.tz_convert('Asia/Jakarta').astype(str)
                                else: df_hist_clean['waktu_lokal'] = "-"
                                cols_target = ['trx_id', 'waktu_lokal', 'user', 'total_bill', 'items_count']
                                for c in cols_target:
                                    if c not in df_hist_clean.columns: df_hist_clean[c] = "-"
                                format_excel(writer, df_hist_clean[cols_target], 'Riwayat Transaksi')
                        st.download_button(label="Klik disini untuk Simpan File", data=buffer.getvalue(), file_name=f"Backup_Toko_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel", key="dl_btn")
                        st.toast("File Backup Siap!", icon="📂")
                    else: st.warning("Data kosong.")
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("DOWNLOAD FORMAT SO (.xlsx)", use_container_width=True):
                    if not df_master.empty:
                        df_ready = df_master[df_master['status'] == 'Ready'].copy()
                        if not df_ready.empty:
                            df_so = df_ready.groupby(['brand', 'sku']).size().reset_index(name='Quantity')
                            df_so['Owner'] = 'Konsinyasi'
                            df_so['Jenis'] = 'Stok'
                            df_so = df_so[['brand', 'sku', 'Owner', 'Jenis', 'Quantity']]
                            df_so.columns = ['Brand', 'SKU', 'Owner', 'Jenis', 'Quantity']
                            buffer_so = io.BytesIO()
                            with pd.ExcelWriter(buffer_so, engine='xlsxwriter') as writer:
                                format_excel(writer, df_so, 'Data Stock Opname')
                            st.download_button(label="Klik disini untuk Simpan File SO", data=buffer.getvalue(), file_name=f"Format_SO_{datetime.now().strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel", key="dl_so_btn")
                            st.toast("File SO Siap!", icon="📋")
                        else: st.warning("Tidak ada stok Ready.")
                    else: st.warning("Data Master Kosong.")
                st.markdown('</div>', unsafe_allow_html=True)

            with col_danger:
                st.markdown('<div class="admin-card-red"><div class="admin-header" style="color:#dc2626">⚠️ Danger Zone</div><p>Hapus data permanen. Hati-hati!</p>', unsafe_allow_html=True)
                hapus_opsi = st.radio("Pilih Data yang akan dihapus:", ["-- Pilih Tindakan --", "1. Hapus Riwayat Transaksi Saja", "2. Hapus Stok Barang Saja", "3. RESET PABRIK (Semua Data)"])
                if hapus_opsi != "-- Pilih Tindakan --":
                    st.warning(f"Anda akan melakukan: {hapus_opsi}")
                    pin_konfirm = st.text_input("Masukkan PIN Konfirmasi:", type="password")
                    if st.button("🔥 JALANKAN PENGHAPUSAN 🔥", type="primary", use_container_width=True):
                        if pin_konfirm == "123456":
                            with st.spinner("Sedang menghapus..."):
                                if "1." in hapus_opsi:
                                    factory_reset('transactions')
                                    st.toast("Riwayat Transaksi Dihapus!", icon="🗑️")
                                    st.success("Riwayat Transaksi Telah Dihapus.")
                                elif "2." in hapus_opsi:
                                    factory_reset('inventory')
                                    st.toast("Stok Dihapus!", icon="🗑️")
                                    st.success("Stok Barang Telah Dikosongkan.")
                                elif "3." in hapus_opsi:
                                    factory_reset('inventory'); factory_reset('transactions'); factory_reset('import_logs')
                                    st.toast("Reset Total Berhasil!", icon="🚀")
                                    st.success("RESET TOTAL BERHASIL! Aplikasi kembali seperti baru.")
                                time.sleep(2); st.rerun()
                        else: st.error("PIN Salah!")
                st.markdown('</div>', unsafe_allow_html=True)
