# ==========================================
# APLIKASI: SN TRACKER PRO (V5.0 Supabase)
# BASE: V4.6 (Scrollable Cart + Copy SN)
# ENGINE: Supabase (PostgreSQL) - QUOTA FREE
# ==========================================

import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime
import time
import io
import plotly.express as px
import re

# --- 1. SETUP HALAMAN ---
st.set_page_config(
    page_title="SN Tracker",
    page_icon="📦",
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
    :root { --brand-blue: #0095DA; --brand-yellow: #F99D1C; }
    div.stButton > button[kind="primary"] {
        background-color: var(--brand-blue); border: none; color: white; font-weight: bold;
        padding: 8px 16px; border-radius: 6px;
    }
    div.stButton > button[kind="primary"]:hover { background-color: #007bb5; }
    div.stButton > button[data-testid="baseButton-secondary"] { border-color: #ff4b4b; color: #ff4b4b; }
    div.stButton > button[data-testid="baseButton-secondary"]:hover { background-color: #fff0f0; border-color: #ff4b4b; color: #ff4b4b; }
    .big-price { font-size: 28px; font-weight: 800; color: var(--brand-yellow); margin-bottom: 5px; display: block; }
    .step-header { background-color: var(--brand-blue); color: white; padding: 8px 15px; border-radius: 6px; margin-bottom: 15px; font-weight: bold; }
    div[data-testid="stVerticalBlock"] .stCode { margin-bottom: 0px !important; }
    .alert-stock { background-color: rgba(255, 0, 0, 0.1); color: #e53935; padding: 10px; border-radius: 5px; border: 1px solid #ef9a9a; margin-bottom: 10px; font-weight: bold; font-size: 14px; }
    .danger-zone { border: 2px solid #e53935; background-color: #ffebee; padding: 20px; border-radius: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- 5. FUNGSI LOGIC SUPABASE ---

def clear_cache():
    """Hapus cache agar data terupdate"""
    get_inventory_df.clear()
    get_history_df.clear()
    get_import_logs.clear()

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def format_rp(val): return f"Rp {val:,.0f}".replace(",", ".")

# --- READ DATA (Cached) ---
@st.cache_data(ttl=300)
def get_inventory_df():
    # Ambil semua data inventory
    # Supabase select * from inventory
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

# --- WRITE DATA (CRUD) ---

def add_stock_batch(user, brand, sku, price, sn_list):
    """Insert bulk ke Supabase (Lebih cepat dr Firestore)"""
    data_to_insert = []
    log_items = []
    
    for sn in sn_list:
        sn = sn.strip()
        if sn:
            item = {
                'sn': sn, 'brand': brand, 'sku': sku, 
                'price': int(price), 'status': 'Ready', 
                'created_at': datetime.now().isoformat()
            }
            data_to_insert.append(item)
            log_items.append(item)
    
    if data_to_insert:
        # Supabase support bulk insert langsung
        try:
            supabase.table('inventory').upsert(data_to_insert).execute()
            
            # Catat Log
            log_data = {
                'timestamp': datetime.now().isoformat(), 'user': user,
                'method': "Manual Input", 'total_items': len(data_to_insert),
                'items_detail': log_items # JSONB support
            }
            supabase.table('import_logs').insert(log_data).execute()
            clear_cache()
            return len(data_to_insert)
        except Exception as e:
            st.error(f"Error Database: {e}")
            return 0
    return 0

def import_stock_from_df(user, df):
    df.columns = [c.lower().strip() for c in df.columns]
    data_to_insert = []
    
    for index, row in df.iterrows():
        sn_val = str(row['sn']).strip()
        if not sn_val or sn_val.lower() == 'nan': continue
        item = {
            'sn': sn_val, 'brand': str(row['brand']), 'sku': str(row['sku']),
            'price': int(row['price']), 'status': 'Ready', 
            'created_at': datetime.now().isoformat()
        }
        data_to_insert.append(item)
    
    if data_to_insert:
        try:
            # Batching per 1000 agar aman
            batch_size = 1000
            for i in range(0, len(data_to_insert), batch_size):
                batch = data_to_insert[i:i + batch_size]
                supabase.table('inventory').upsert(batch).execute()
            
            # Log
            log_data = {
                'timestamp': datetime.now().isoformat(), 'user': user,
                'method': "Excel Import", 'total_items': len(data_to_insert),
                'items_detail': data_to_insert
            }
            supabase.table('import_logs').insert(log_data).execute()
            clear_cache()
            return True, f"Berhasil Import {len(data_to_insert)} Data!"
        except Exception as e:
            return False, f"Error: {e}"
    return False, "Data Kosong"

def process_checkout(user, cart_items):
    total = sum(item['price'] for item in cart_items)
    sn_sold = [item['sn'] for item in cart_items]
    trx_id = f"TRX-{int(time.time())}" # Simple ID generation
    
    try:
        # 1. Update Status Inventory (Bulk Update)
        # Di Supabase harus update satu-satu atau pakai 'in' filter jika value sama. 
        # Kita update status jadi 'Sold' untuk list SN ini.
        supabase.table('inventory').update({
            'status': 'Sold', 
            'sold_at': datetime.now().isoformat()
        }).in_('sn', sn_sold).execute()
        
        # 2. Catat Transaksi
        trx_data = {
            'trx_id': trx_id,
            'timestamp': datetime.now().isoformat(),
            'user': user,
            'total_bill': total,
            'items_count': len(sn_sold),
            'item_details': cart_items # JSONB Store
        }
        supabase.table('transactions').insert(trx_data).execute()
        
        clear_cache()
        return trx_id, total
    except Exception as e:
        st.error(f"Transaksi Gagal: {e}")
        return None, 0

def update_stock_price(sn, new_price):
    supabase.table('inventory').update({'price': int(new_price)}).eq('sn', sn).execute()
    clear_cache()

def delete_stock(sn):
    supabase.table('inventory').delete().eq('sn', sn).execute()
    clear_cache()

def factory_reset(table_name):
    # Hapus semua data (Dangerous)
    # Supabase tidak ada 'delete all' tanpa where, jadi pakai not eq dummy
    supabase.table(table_name).delete().neq('sn' if table_name == 'inventory' else 'trx_id', 'dummy_val').execute()
    clear_cache()

# --- 6. LOGIN ---
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align:center; color:#0095DA;'>SN <span style='color:#F99D1C;'>TRACKER</span></h1>", unsafe_allow_html=True)
            st.caption("v5.0 Supabase Engine", unsafe_allow_html=True)
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
# Manual refresh button utk update cache
with st.sidebar:
    st.markdown("### 📦 SN Tracker")
    st.markdown(f"User: **{st.session_state.user_role}**")
    menu = st.radio("Menu Utama", ["🛒 Kasir", "📦 Gudang", "🔧 Admin Tools"] if st.session_state.user_role == "ADMIN" else ["🛒 Kasir", "📦 Gudang"], label_visibility="collapsed")
    st.divider()
    
    if st.button("🔄 Refresh Data"):
        clear_cache()
        st.toast("Data direfresh!")
        time.sleep(0.5)
        st.rerun()
        
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
    # Load data
    df_master = get_inventory_df()
    
    c_product, c_cart = st.columns([1.8, 1])
    with c_product:
        st.markdown('<div class="step-header">1️⃣ Cari & Scan Barang</div>', unsafe_allow_html=True)
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                df_ready['display'] = "[" + df_ready['brand'] + "] " + df_ready['sku'] + " (" + df_ready['price'].apply(format_rp) + ")"
                search_options = sorted(df_ready['display'].unique())
                pilih_barang = st.selectbox("🔍 Cari Produk:", ["-- Pilih Produk --"] + search_options, key=f"sb_{st.session_state.search_key}")
                
                if pilih_barang != "-- Pilih Produk --":
                    rows = df_ready[df_ready['display'] == pilih_barang]
                    if not rows.empty:
                        item = rows.iloc[0]; sku = item['sku']
                        st.markdown(f"<span class='big-price'>{format_rp(item['price'])}</span>", unsafe_allow_html=True)
                        st.caption(f"Brand: {item['brand']} | SKU: {sku}")
                        sn_cart = [x['sn'] for x in st.session_state.keranjang]
                        avail = df_ready[(df_ready['sku'] == sku) & (~df_ready['sn'].isin(sn_cart))]
                        st.divider()
                        col_sn, col_add = st.columns([2, 1])
                        with col_sn:
                            sn_list_sorted = sorted(avail['sn'].tolist(), key=natural_sort_key)
                            p_sn = st.multiselect("Pilih SN:", sn_list_sorted, placeholder="Pilih SN...")
                            st.write(f"Stok: **{len(avail)}** Unit")
                        with col_add:
                            st.write(""); st.write("") 
                            if st.button("TAMBAH ➕", type="primary", use_container_width=True):
                                if p_sn:
                                    for s in p_sn: st.session_state.keranjang.append(avail[avail['sn']==s].iloc[0].to_dict())
                                    st.session_state.search_key += 1; st.toast("Masuk Keranjang!", icon="🛒"); time.sleep(0.1); st.rerun()
                                else: st.warning("Pilih SN dulu")
                    else: st.warning("Barang tidak ditemukan.")
            else: st.warning("Stok Gudang Kosong.")
        else: st.warning("Database Kosong.")

    with c_cart:
        st.markdown('<div class="step-header">2️⃣ Keranjang</div>', unsafe_allow_html=True)
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
                    if tid:
                        st.session_state.keranjang = []; st.balloons(); st.success("Transaksi Sukses!")
                        st.session_state.last_trx = {'id': tid, 'total': tbil}
                        st.rerun()
                if st.button("❌ Batal", use_container_width=True):
                    st.session_state.keranjang = []; st.rerun()
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
        st.subheader("Ringkasan Stok Gudang")
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                stok_rekap = df_ready.groupby(['brand', 'sku', 'price']).size().reset_index(name='Total Stok')
                stok_rekap = stok_rekap.sort_values(by=['brand', 'sku'])
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Unit", f"{len(df_ready)}")
                c2.metric("Nilai Aset", format_rp(df_ready['price'].sum()))
                c3.metric("Jenis Produk", f"{len(stok_rekap)}")
                max_stok = int(stok_rekap['Total Stok'].max())
                st.dataframe(stok_rekap, use_container_width=True, column_config={"price": st.column_config.NumberColumn("Harga", format="Rp %d"), "Total Stok": st.column_config.ProgressColumn("Stok", format="%d", min_value=0, max_value=max_stok)}, hide_index=True)
            else: st.info("Gudang Kosong.")
        else: st.info("Database Kosong.")

    with tabs[1]:
        st.subheader("Detail SN")
        if not df_master.empty:
            sc, sf = st.columns(2)
            q = sc.text_input("Cari SN/SKU:")
            fb = sf.selectbox("Brand", ["All"] + sorted(df_master['brand'].unique().tolist()))
            dv = df_master.copy()
            if q: dv = dv[dv['sku'].str.contains(q, case=False) | dv['sn'].str.contains(q, case=False)]
            if fb != "All": dv = dv[dv['brand'] == fb]
            st.dataframe(dv[['sn','sku','brand','price','status']], use_container_width=True)

    with tabs[2]:
        if st.session_state.user_role == "ADMIN":
            st.subheader("Input Stok")
            mode = st.radio("Metode:", ["Manual", "Upload Excel"], horizontal=True)
            if mode == "Manual":
                with st.form("in"):
                    c1,c2,c3 = st.columns(3); b=c1.text_input("Brand"); s=c2.text_input("SKU"); p=c3.number_input("Harga", step=5000)
                    sn = st.text_area("SN (Enter pemisah):")
                    if st.form_submit_button("SIMPAN", type="primary"):
                        if b and s and sn: 
                            cnt = add_stock_batch(st.session_state.user_role, b, s, p, sn.strip().split('\n'))
                            if cnt > 0: st.success(f"Masuk {cnt} item!"); time.sleep(1); st.rerun()
            else:
                uf = st.file_uploader("Excel/CSV", type=['xlsx','csv'])
                if uf and st.button("PROSES", type="primary"):
                    df = pd.read_csv(uf) if uf.name.endswith('.csv') else pd.read_excel(uf)
                    ok, msg = import_stock_from_df(st.session_state.user_role, df)
                    if ok: st.success(msg); time.sleep(2); st.rerun()
                    else: st.error(msg)
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
            st.subheader("Edit Data")
            if st.text_input("PIN Admin:", type="password") == "123456":
                src = st.text_input("Cari SN Edit:")
                if src and not df_master.empty:
                    de = df_master[df_master['sn'].str.contains(src, case=False)]
                    for i, r in de.iterrows():
                        with st.expander(f"{r['sku']} ({r['sn']})"):
                            np = st.number_input("Harga", value=int(r['price']), key=f"p{r['sn']}")
                            if st.button("Update", key=f"u{r['sn']}"): update_stock_price(r['sn'], np); st.rerun()
                            if st.button("Hapus", key=f"d{r['sn']}", type="primary"): delete_stock(r['sn']); st.rerun()

# === ADMIN TOOLS ===
elif menu == "🔧 Admin Tools":
    if st.session_state.user_role == "ADMIN":
        st.title("🔧 Admin Tools")
        tab1, tab2 = st.tabs(["📊 Analitik", "💾 Backup & Reset"])
        
        with tab1:
            df_hist = get_history_df()
            if not df_hist.empty:
                df_hist['waktu'] = pd.to_datetime(df_hist['timestamp'])
                df_hist['Tgl'] = df_hist['waktu'].dt.date
                m1, m2 = st.columns(2)
                m1.metric("Omzet", format_rp(df_hist['total_bill'].sum()))
                m2.metric("Trx", len(df_hist))
                fig = px.line(df_hist.groupby('Tgl')['total_bill'].sum().reset_index(), x='Tgl', y='total_bill', title="Tren Harian")
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("Belum ada transaksi")

        with tab2:
            st.info("Backup Data")
            if st.button("Hapus Semua Data (Danger Zone)"):
                st.session_state.reset_mode = True
            
            if 'reset_mode' in st.session_state and st.session_state.reset_mode:
                if st.text_input("PIN Konfirmasi:", type="password") == "123456":
                    if st.button(" 🔥 YA, RESET TOTAL 🔥"):
                        factory_reset('inventory')
                        factory_reset('transactions')
                        st.success("Reset Berhasil"); time.sleep(2); st.rerun()