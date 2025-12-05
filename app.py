# ==========================================
# APLIKASI: SN TRACKER PRO (V4.5 Logout Confirm)
# ENGINE: Google Firestore
# UPDATE: Tombol Logout Pakai Konfirmasi (Anti-Kepencet)
# ==========================================

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
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

# --- 2. KONEKSI DATABASE (FIREBASE) ---
@st.cache_resource
def init_db():
    try:
        if not firebase_admin._apps:
            if 'firestore_key' in st.secrets:
                key_dict = dict(st.secrets['firestore_key'])
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            else:
                cred = credentials.Certificate("firestore_key.json") 
                firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"⚠️ Gagal koneksi Database: {e}")
        st.stop()

db = init_db()

# --- 3. STATE MANAGEMENT ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_role' not in st.session_state: st.session_state.user_role = ""
if 'keranjang' not in st.session_state: st.session_state.keranjang = []
if 'search_key' not in st.session_state: st.session_state.search_key = 0 
if 'confirm_logout' not in st.session_state: st.session_state.confirm_logout = False

# --- 4. CSS CUSTOMIZATION ---
st.markdown("""
    <style>
    :root {
        --brand-blue: #0095DA;
        --brand-yellow: #F99D1C;
    }
    
    div.stButton > button[kind="primary"] {
        background-color: var(--brand-blue); border: none; color: white; font-weight: bold;
        padding: 8px 16px; border-radius: 6px;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #007bb5;
    }
    /* Tombol Logout Khusus (Merah Tipis) */
    div.stButton > button[data-testid="baseButton-secondary"] {
        border-color: #ff4b4b; color: #ff4b4b;
    }
    div.stButton > button[data-testid="baseButton-secondary"]:hover {
        background-color: #fff0f0; border-color: #ff4b4b; color: #ff4b4b;
    }
    
    .big-price { 
        font-size: 28px; font-weight: 800; color: var(--brand-yellow); 
        margin-bottom: 5px; display: block; 
    }
    .step-header { 
        background-color: var(--brand-blue); color: white; padding: 8px 15px; 
        border-radius: 6px; margin-bottom: 15px; font-weight: bold; 
    }
    div[data-testid="stVerticalBlock"] .stCode {
        margin-bottom: 0px !important;
    }
    .alert-stock {
        background-color: rgba(255, 0, 0, 0.1); color: #e53935; padding: 10px; 
        border-radius: 5px; border: 1px solid #ef9a9a; margin-bottom: 10px; font-weight: bold; font-size: 14px;
    }
    .metric-card {
        background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #0095DA;
    }
    </style>
""", unsafe_allow_html=True)

# --- 5. FUNGSI LOGIC DATABASE & UTILS ---

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def format_rp(val): return f"Rp {val:,.0f}".replace(",", ".")

def get_inventory_df():
    docs = db.collection('inventory').stream()
    data = [{'id': doc.id, **doc.to_dict()} for doc in docs]
    if not data: return pd.DataFrame(columns=['brand', 'sku', 'price', 'sn', 'status'])
    return pd.DataFrame(data)

def get_history_df():
    docs = db.collection('transactions').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
    data = [{'id': doc.id, **doc.to_dict()} for doc in docs]
    if not data: return pd.DataFrame(columns=['trx_id', 'timestamp', 'user', 'total_bill'])
    return pd.DataFrame(data)

def get_import_logs():
    docs = db.collection('import_logs').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(20).stream()
    data = [{'id': doc.id, **doc.to_dict()} for doc in docs]
    return data

def log_import_activity(user, method, items_df):
    log_ref = db.collection('import_logs').document()
    items_list = items_df[['brand', 'sku', 'sn', 'price']].to_dict('records')
    log_data = {
        'log_id': log_ref.id, 'timestamp': datetime.now(), 'user': user,
        'method': method, 'total_items': len(items_df), 'items_detail': items_list
    }
    log_ref.set(log_data)

def add_stock_batch(user, brand, sku, price, sn_list):
    batch = db.batch(); count = 0; total_added = 0; log_items = []
    for sn in sn_list:
        sn = sn.strip()
        if sn:
            doc_ref = db.collection('inventory').document(sn)
            batch.set(doc_ref, {'brand': brand, 'sku': sku, 'price': int(price), 'sn': sn, 'status': 'Ready', 'created_at': datetime.now()})
            log_items.append({'brand': brand, 'sku': sku, 'sn': sn, 'price': int(price)})
            count += 1
            if count >= 400: batch.commit(); batch = db.batch(); total_added += count; count = 0
    if count > 0: batch.commit(); total_added += count
    if total_added > 0: log_import_activity(user, "Manual Input", pd.DataFrame(log_items))
    return total_added

def import_stock_from_df(user, df):
    df.columns = [c.lower().strip() for c in df.columns]
    required_cols = ['brand', 'sku', 'price', 'sn']
    missing = [c for c in required_cols if c not in df.columns]
    if missing: return False, f"Kolom hilang: {', '.join(missing)}"
    batch = db.batch(); count = 0; total_imported = 0; progress_bar = st.progress(0); total_rows = len(df); log_items = []
    for index, row in df.iterrows():
        sn_val = str(row['sn']).strip()
        if not sn_val or sn_val.lower() == 'nan': continue
        doc_ref = db.collection('inventory').document(sn_val)
        item_data = {'brand': str(row['brand']), 'sku': str(row['sku']), 'price': int(row['price']), 'sn': sn_val, 'status': 'Ready', 'created_at': datetime.now()}
        batch.set(doc_ref, item_data); log_items.append(item_data); count += 1
        if count >= 400: batch.commit(); batch = db.batch(); total_imported += count; count = 0; progress_bar.progress(min(index / total_rows, 1.0))
    if count > 0: batch.commit(); total_imported += count
    progress_bar.empty()
    if total_imported > 0: log_import_activity(user, "Excel Import", pd.DataFrame(log_items))
    return True, f"Import {total_imported} Data!"

def update_stock_price(sn, new_price):
    db.collection('inventory').document(sn).update({'price': int(new_price)})

def delete_stock(sn):
    db.collection('inventory').document(sn).delete()

def delete_collection_batch(coll_name, batch_size=100):
    docs = db.collection(coll_name).limit(batch_size).stream()
    deleted = 0; batch = db.batch()
    for doc in docs: batch.delete(doc.reference); deleted += 1
    if deleted > 0: batch.commit(); return deleted + delete_collection_batch(coll_name, batch_size)
    return 0

def process_checkout(user, cart_items):
    batch = db.batch(); total = sum(item['price'] for item in cart_items); sn_sold = [item['sn'] for item in cart_items]
    for item in cart_items:
        doc_ref = db.collection('inventory').document(item['sn'])
        batch.update(doc_ref, {'status': 'Sold', 'sold_at': datetime.now()})
    trx_ref = db.collection('transactions').document()
    trx_id = trx_ref.id[:8].upper()
    batch.set(trx_ref, {'trx_id': trx_id, 'timestamp': datetime.now(), 'user': user, 'items': sn_sold, 'item_details': cart_items, 'total_bill': total, 'items_count': len(sn_sold)})
    batch.commit(); return trx_id, total

# --- 6. LOGIN ---
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align:center; color:#0095DA;'>SN <span style='color:#F99D1C;'>TRACKER</span></h1>", unsafe_allow_html=True)
            st.caption("v4.5 Logout Confirmation", unsafe_allow_html=True)
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
    
    menu_items = ["🛒 Kasir", "📦 Gudang", "🔧 Admin Tools"] if st.session_state.user_role == "ADMIN" else ["🛒 Kasir", "📦 Gudang"]
    menu = st.radio("Menu Utama", menu_items, label_visibility="collapsed")
    
    st.divider()
    
    if not df_master.empty:
        stok_ready = df_master[df_master['status'] == 'Ready']
        stok_count = stok_ready.groupby(['brand', 'sku']).size().reset_index(name='jumlah')
        stok_tipis = stok_count[stok_count['jumlah'] < 5]
        if not stok_tipis.empty: st.markdown(f"<div class='alert-stock'>🔔 {len(stok_tipis)} Item Stok Menipis</div>", unsafe_allow_html=True)
    
    st.markdown("<br>" * 3, unsafe_allow_html=True) 
    st.markdown("---")
    
    # --- LOGOUT DENGAN KONFIRMASI ---
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
        st.markdown('<div class="step-header">1️⃣ Cari & Scan Barang</div>', unsafe_allow_html=True)
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                df_ready['display'] = "[" + df_ready['brand'] + "] " + df_ready['sku'] + " (" + df_ready['price'].apply(format_rp) + ")"
                search_options = sorted(df_ready['display'].unique())
                pilih_barang = st.selectbox("🔍 Cari Produk (Scan Barcode / Ketik):", ["-- Pilih Produk --"] + search_options, key=f"sb_{st.session_state.search_key}")
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
                            p_sn = st.multiselect("Pilih Serial Number (SN):", sn_list_sorted, placeholder="Pilih SN...")
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
        with st.container(border=True):
            if st.session_state.keranjang:
                tot = 0
                st.caption("Klik tombol kecil di kanan SN untuk Copy.")
                for i, x in enumerate(st.session_state.keranjang):
                    tot += x['price']
                    st.markdown(f"**{x['sku']}**")
                    c_sn_code, c_price = st.columns([2.5, 1]) 
                    with c_sn_code: st.code(x['sn'], language="text") 
                    with c_price: st.markdown(f"<div style='text-align:right; margin-top: 5px; font-weight:bold;'>{format_rp(x['price'])}</div>", unsafe_allow_html=True)
                    st.divider()
                st.markdown(f"<div style='text-align:right'>Total Tagihan<br><span class='big-price'>{format_rp(tot)}</span></div>", unsafe_allow_html=True)
                if st.button("✅ BAYAR SEKARANG", type="primary", use_container_width=True):
                    tid, tbil = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                    st.session_state.keranjang = []; st.balloons(); st.success("Transaksi Sukses!")
                    st.session_state.last_trx = {'id': tid, 'total': tbil}
                    st.rerun()
                if st.button("❌ Batal", use_container_width=True):
                    st.session_state.keranjang = []; st.rerun()
            else:
                if 'last_trx' in st.session_state and st.session_state.last_trx:
                    st.success("✅ Transaksi Berhasil!")
                    st.write(f"ID: {st.session_state.last_trx['id']}")
                    st.write(f"Total: {format_rp(st.session_state.last_trx['total'])}")
                    if st.button("Tutup"): del st.session_state.last_trx; st.rerun()
                else: st.info("Keranjang Kosong")

# === GUDANG ===
elif menu == "📦 Gudang":
    st.title("📦 Manajemen Gudang")
    tabs = st.tabs(["📊 Dashboard Stok", "🔍 Cek Detail", "➕ Input Barang", "📜 Riwayat Import", "🛠️ Edit/Hapus"])
    
    with tabs[0]:
        st.subheader("Ringkasan Stok Gudang")
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                stok_rekap = df_ready.groupby(['brand', 'sku', 'price']).size().reset_index(name='Total Stok')
                stok_rekap = stok_rekap.sort_values(by=['brand', 'sku'])
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Unit Barang", f"{len(df_ready)} Unit")
                c2.metric("Total Nilai Aset", format_rp(df_ready['price'].sum()))
                c3.metric("Jenis Produk (SKU)", f"{len(stok_rekap)} Jenis")
                max_stok_val = int(stok_rekap['Total Stok'].max()) if not stok_rekap.empty else 100
                st.markdown("### Tabel Rekapitulasi")
                st.dataframe(stok_rekap, use_container_width=True, column_config={"price": st.column_config.NumberColumn("Harga Satuan", format="Rp %d"), "Total Stok": st.column_config.ProgressColumn("Ketersediaan", format="%d", min_value=0, max_value=max_stok_val)}, hide_index=True)
            else: st.info("Gudang Kosong (Belum ada stok Ready).")
        else: st.info("Database Kosong.")

    with tabs[1]:
        st.subheader("Daftar Serial Number (Detail)")
        if not df_master.empty:
            sc, sf = st.columns(2)
            q = sc.text_input("Cari SN/SKU:", placeholder="Ketik nomor SN...")
            fb = sf.selectbox("Filter Brand", ["All"] + sorted(df_master['brand'].unique().tolist()))
            dv = df_master.copy()
            if q: dv = dv[dv['sku'].str.contains(q, case=False) | dv['sn'].str.contains(q, case=False)]
            if fb != "All": dv = dv[dv['brand'] == fb]
            def highlight_status(val): return f'background-color: {"#d4edda" if val == "Ready" else "#f8d7da"}'
            st.dataframe(dv[['sn','sku','brand','price','status']].style.applymap(highlight_status, subset=['status']), use_container_width=True)

    with tabs[2]:
        if st.session_state.user_role == "ADMIN":
            st.subheader("Input Stok Baru")
            mode = st.radio("Metode Input:", ["Manual Input", "Upload Excel"], horizontal=True)
            if mode == "Manual Input":
                with st.form("in"):
                    c1,c2,c3 = st.columns(3); b=c1.text_input("Brand"); s=c2.text_input("SKU"); p=c3.number_input("Harga", step=5000)
                    sn = st.text_area("List SN (Pisahkan dengan Enter):", height=150)
                    if st.form_submit_button("SIMPAN KE DATABASE", type="primary"):
                        if b and s and sn: 
                            cnt = add_stock_batch(st.session_state.user_role, b, s, p, sn.strip().split('\n'))
                            st.success(f"Berhasil input {cnt} unit!"); time.sleep(1); st.rerun()
            else:
                st.info("Format Excel: Kolom **Brand, SKU, Price, SN**")
                uf = st.file_uploader("Pilih File Excel/CSV", type=['xlsx','csv'])
                if uf and st.button("PROSES IMPORT", type="primary"):
                    df = pd.read_csv(uf) if uf.name.endswith('.csv') else pd.read_excel(uf)
                    ok, msg = import_stock_from_df(st.session_state.user_role, df)
                    if ok: st.success(msg); time.sleep(2); st.rerun()
                    else: st.error(msg)
        else: st.warning("Akses Input Khusus Admin.")

    with tabs[3]:
        st.subheader("📜 Log Riwayat Import")
        if st.session_state.user_role == "ADMIN":
            logs = get_import_logs()
            if logs:
                for log in logs:
                    ts = log['timestamp']; ts_str = ts.strftime("%d %b %Y, %H:%M") if isinstance(ts, datetime) else "-"
                    with st.expander(f"{ts_str} | {log['method']} | Oleh: {log['user']} ({log['total_items']} Item)"):
                        if 'items_detail' in log and log['items_detail']: st.dataframe(pd.DataFrame(log['items_detail']), use_container_width=True)
                        else: st.write("Detail tidak tersedia.")
            else: st.info("Belum ada riwayat import.")
        else: st.warning("Akses Khusus Admin.")

    with tabs[4]:
        if st.session_state.user_role == "ADMIN":
            st.subheader("Koreksi Data")
            if st.text_input("PIN Admin:", type="password") == "123456":
                src = st.text_input("Cari SN yang mau diedit:")
                if src and not df_master.empty:
                    de = df_master[df_master['sn'].str.contains(src, case=False)]
                    for i, r in de.iterrows():
                        with st.expander(f"{r['sku']} ({r['sn']})"):
                            np = st.number_input("Harga Baru", value=int(r['price']), key=f"p{r['sn']}")
                            if st.button("Update Harga", key=f"u{r['sn']}"): update_stock_price(r['sn'], np); st.rerun()
                            if st.button("Hapus Barang", key=f"d{r['sn']}", type="primary"): delete_stock(r['sn']); st.rerun()

# === ADMIN TOOLS ===
elif menu == "🔧 Admin Tools":
    if st.session_state.user_role == "ADMIN":
        st.title("🔧 Admin Tools")
        tab_analitik, tab_tools = st.tabs(["📊 Analitik Bisnis", "💾 Backup & Reset"])
        
        with tab_analitik:
            df_hist = get_history_df()
            if not df_hist.empty:
                df_hist['waktu_lokal'] = pd.to_datetime(df_hist['timestamp']).dt.tz_convert('Asia/Jakarta')
                df_hist['Tanggal'] = df_hist['waktu_lokal'].dt.date
                c_d1, c_d2 = st.columns(2)
                start_date = c_d1.date_input("Dari", value=datetime.now().date() - timedelta(days=7))
                end_date = c_d2.date_input("Sampai", value=datetime.now().date())
                df_filt = df_hist[(df_hist['Tanggal'] >= start_date) & (df_hist['Tanggal'] <= end_date)]
                if not df_filt.empty:
                    m1, m2 = st.columns(2)
                    m1.metric("Total Omzet", format_rp(df_filt['total_bill'].sum()))
                    m2.metric("Transaksi", len(df_filt))
                    st.markdown("---")
                    col_g1, col_g2 = st.columns([2,1])
                    with col_g1:
                        daily = df_filt.groupby('Tanggal')['total_bill'].sum().reset_index()
                        fig = px.line(daily, x='Tanggal', y='total_bill', title="Tren Harian", markers=True)
                        st.plotly_chart(fig, use_container_width=True)
                    with col_g2:
                        fig2 = px.pie(df_filt, names='user', title="Performa User", hole=0.4)
                        st.plotly_chart(fig2, use_container_width=True)
                else: st.info("Data kosong di rentang tanggal ini.")
            else: st.info("Belum ada riwayat transaksi.")

        with tab_tools:
            st.info("💡 Halaman ini digunakan untuk download data atau menghapus database.")
            c_back, c_danger = st.columns([1, 1.2])
            with c_back:
                st.markdown("### 1. Backup Data (Excel)")
                if not df_master.empty:
                    out_stok = io.BytesIO()
                    df_down_stok = df_master.copy()
                    for col in df_down_stok.columns:
                        if pd.api.types.is_datetime64_any_dtype(df_down_stok[col]):
                            df_down_stok[col] = df_down_stok[col].astype(str)
                    with pd.ExcelWriter(out_stok, engine='xlsxwriter') as writer:
                        df_down_stok.to_excel(writer, index=False, sheet_name='Stok_Gudang')
                    st.download_button("📥 Download Master Stok (.xlsx)", out_stok.getvalue(), "Backup_Stok.xlsx", "application/vnd.ms-excel", use_container_width=True)
                
                df_hist_all = get_history_df()
                if not df_hist_all.empty:
                    df_clean = df_hist_all.copy()
                    if 'timestamp' in df_clean.columns: df_clean['waktu_lokal'] = pd.to_datetime(df_clean['timestamp']).dt.tz_convert('Asia/Jakarta').astype(str)
                    else: df_clean['waktu_lokal'] = "-"
                    target_cols = ['trx_id', 'waktu_lokal', 'user', 'total_bill', 'items_count']
                    for col in target_cols:
                        if col not in df_clean.columns: df_clean[col] = 0 if col in ['total_bill', 'items_count'] else "-"
                    out_hist = io.BytesIO()
                    with pd.ExcelWriter(out_hist, engine='xlsxwriter') as writer:
                        df_clean[target_cols].to_excel(writer, index=False, sheet_name='Riwayat_Transaksi')
                    st.download_button("📥 Download Riwayat Transaksi (.xlsx)", out_hist.getvalue(), "Backup_Transaksi.xlsx", "application/vnd.ms-excel", use_container_width=True)
                else: st.warning("Belum ada data transaksi.")

            with c_danger:
                st.error("### 2. Danger Zone (Hapus Data)")
                with st.container(border=True):
                    st.warning("⚠️ Perhatian: Data yang dihapus TIDAK BISA kembali.")
                    action = st.radio("Pilih Tindakan:", ["Hapus Riwayat Transaksi Saja", "Hapus Semua Stok Barang", "FACTORY RESET (Hapus Semuanya)"])
                    pin_confirm = st.text_input("Masukkan PIN Keamanan:", type="password", placeholder="PIN Admin")
                    if st.button("🔥 EKSEKUSI PENGHAPUSAN", type="primary", use_container_width=True):
                        if pin_confirm == "123456":
                            with st.spinner("Sedang menghapus data di Cloud..."):
                                if action == "Hapus Riwayat Transaksi Saja":
                                    count = delete_collection_batch('transactions', 100)
                                    st.success(f"Berhasil menghapus {count} data transaksi!")
                                elif action == "Hapus Semua Stok Barang":
                                    count = delete_collection_batch('inventory', 100)
                                    st.success(f"Berhasil mengosongkan gudang ({count} item)!")
                                elif action == "FACTORY RESET (Hapus Semuanya)":
                                    c1 = delete_collection_batch('transactions', 100); c2 = delete_collection_batch('inventory', 100)
                                    delete_collection_batch('import_logs', 100)
                                    st.success(f"RESET TOTAL BERHASIL! ({c1} Trx, {c2} Stok)")
                                time.sleep(2); st.rerun()
                        else: st.error("PIN SALAH! Akses ditolak.")
    else: st.error("Akses Khusus Admin")
