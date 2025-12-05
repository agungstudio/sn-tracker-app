# ==========================================
# APLIKASI: SN TRACKER PRO (V3.6 Copy Feature)
# ENGINE: Google Firestore
# FITUR UTAMA: One-Click Copy SN untuk Kasir
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
    page_title="Blibli POS Gold",
    page_icon="💎",
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
    .big-price { 
        font-size: 28px; font-weight: 800; color: var(--brand-yellow); 
        margin-bottom: 5px; display: block; 
    }
    .step-header { 
        background-color: var(--brand-blue); color: white; padding: 8px 15px; 
        border-radius: 6px; margin-bottom: 15px; font-weight: bold; 
    }
    .stCode { font-family: 'Courier New', monospace; font-weight: bold; }
    .alert-stock {
        background-color: rgba(255, 0, 0, 0.1); color: #e53935; padding: 10px; 
        border-radius: 5px; border: 1px solid #ef9a9a; margin-bottom: 10px; font-weight: bold; font-size: 14px;
    }
    .danger-zone {
        border: 2px solid #e53935; background-color: #ffebee; padding: 20px; border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 5. FUNGSI LOGIC DATABASE & UTILS ---

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

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

def add_stock_batch(brand, sku, price, sn_list):
    batch = db.batch()
    count = 0
    for sn in sn_list:
        sn = sn.strip()
        if sn:
            doc_ref = db.collection('inventory').document(sn)
            batch.set(doc_ref, {
                'brand': brand, 'sku': sku, 'price': int(price),
                'sn': sn, 'status': 'Ready', 'created_at': datetime.now()
            })
            count += 1
    batch.commit()
    return count

def import_stock_from_df(df):
    df.columns = [c.lower().strip() for c in df.columns]
    required_cols = ['brand', 'sku', 'price', 'sn']
    missing = [c for c in required_cols if c not in df.columns]
    if missing: return False, f"Kolom hilang: {', '.join(missing)}"
    
    batch = db.batch(); count = 0; total_imported = 0
    progress_bar = st.progress(0); total_rows = len(df)
    
    for index, row in df.iterrows():
        sn_val = str(row['sn']).strip()
        if not sn_val or sn_val.lower() == 'nan': continue
        doc_ref = db.collection('inventory').document(sn_val)
        batch.set(doc_ref, {
            'brand': str(row['brand']), 'sku': str(row['sku']),
            'price': int(row['price']), 'sn': sn_val,
            'status': 'Ready', 'created_at': datetime.now()
        })
        count += 1
        if count >= 400:
            batch.commit(); batch = db.batch(); total_imported += count; count = 0
            progress_bar.progress(min(index / total_rows, 1.0))
            
    if count > 0: batch.commit(); total_imported += count
    progress_bar.empty(); return True, f"Import {total_imported} Data!"

def update_stock_price(sn, new_price):
    db.collection('inventory').document(sn).update({'price': int(new_price)})

def delete_stock(sn):
    db.collection('inventory').document(sn).delete()

def delete_collection_batch(coll_name, batch_size=100):
    docs = db.collection(coll_name).limit(batch_size).stream()
    deleted = 0
    batch = db.batch()
    for doc in docs:
        batch.delete(doc.reference)
        deleted += 1
    if deleted > 0:
        batch.commit()
        return deleted + delete_collection_batch(coll_name, batch_size)
    return 0

def process_checkout(user, cart_items):
    batch = db.batch()
    total = sum(item['price'] for item in cart_items)
    sn_sold = [item['sn'] for item in cart_items]
    for item in cart_items:
        doc_ref = db.collection('inventory').document(item['sn'])
        batch.update(doc_ref, {'status': 'Sold', 'sold_at': datetime.now()})
    trx_ref = db.collection('transactions').document()
    trx_id = trx_ref.id[:8].upper()
    batch.set(trx_ref, {
        'trx_id': trx_id, 'timestamp': datetime.now(),
        'user': user, 'items': sn_sold, 'item_details': cart_items,
        'total_bill': total, 'items_count': len(sn_sold)
    })
    batch.commit()
    return trx_id, total

def format_rp(val): return f"Rp {val:,.0f}".replace(",", ".")

# --- 6. LOGIN ---
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align:center; color:#0095DA;'>BLIBLI <span style='color:#F99D1C;'>POS</span></h1>", unsafe_allow_html=True)
            st.caption("v3.6 Quick Copy Update", unsafe_allow_html=True)
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
    st.markdown("### 💎 Blibli POS")
    st.caption(f"User: **{st.session_state.user_role}**")
    menu_items = ["🛒 Transaksi", "📦 Gudang", "🔧 Admin Tools"] if st.session_state.user_role == "ADMIN" else ["🛒 Transaksi", "📦 Gudang"]
    menu = st.radio("Navigasi", menu_items, label_visibility="collapsed")
    st.divider()
    if not df_master.empty:
        stok_ready = df_master[df_master['status'] == 'Ready']
        stok_count = stok_ready.groupby(['brand', 'sku']).size().reset_index(name='jumlah')
        stok_tipis = stok_count[stok_count['jumlah'] < 5]
        if not stok_tipis.empty: st.markdown(f"<div class='alert-stock'>🔔 {len(stok_tipis)} Item Stok Menipis</div>", unsafe_allow_html=True)
    st.markdown("---")
    if st.button("🚪 Logout"): st.session_state.logged_in = False; st.session_state.keranjang = []; st.rerun()

# --- 8. KONTEN UTAMA ---

# === KASIR ===
if menu == "🛒 Transaksi":
    st.title("🛒 Kasir Point of Sales")
    
    c_product, c_cart = st.columns([1.8, 1])
    
    with c_product:
        st.markdown('<div class="step-header">1️⃣ Cari & Scan Barang</div>', unsafe_allow_html=True)
        
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                df_ready['display'] = "[" + df_ready['brand'] + "] " + df_ready['sku'] + " (" + df_ready['price'].apply(format_rp) + ")"
                search_options = sorted(df_ready['display'].unique())
                
                pilih_barang = st.selectbox(
                    "🔍 Cari Produk (Scan Barcode / Ketik):", 
                    ["-- Pilih Produk --"] + search_options, 
                    key=f"sb_{st.session_state.search_key}",
                )
                
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
                            # Natural Sorting
                            sn_list_sorted = sorted(avail['sn'].tolist(), key=natural_sort_key)
                            p_sn = st.multiselect("Pilih Serial Number (SN):", sn_list_sorted, placeholder="Pilih SN...")
                            st.write(f"Stok: **{len(avail)}** Unit")
                        
                        with col_add:
                            st.write("") 
                            st.write("") 
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
                for i, x in enumerate(st.session_state.keranjang):
                    tot += x['price']
                    c1, c2 = st.columns([2,1])
                    c1.markdown(f"**{x['sku']}**\n<span style='font-size:12px;color:#666'>{x['sn']}</span>", unsafe_allow_html=True)
                    c2.markdown(f"<div style='text-align:right'>{format_rp(x['price'])}</div>", unsafe_allow_html=True)
                    st.divider()
                
                # FITUR BARU: COPY SN OTOMATIS
                st.info("📋 **Copy SN (Paste ke POS Toko):**")
                sn_string = "\n".join([item['sn'] for item in st.session_state.keranjang])
                st.code(sn_string, language="text") # Blok ini punya tombol copy bawaan

                st.markdown(f"<div style='text-align:right'>Total Tagihan<br><span class='big-price'>{format_rp(tot)}</span></div>", unsafe_allow_html=True)
                
                if st.button("✅ BAYAR SEKARANG", type="primary", use_container_width=True):
                    tid, tbil = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                    
                    # Simpan data sementara untuk ditampilkan setelah reload
                    st.session_state.last_trx = {'id': tid, 'total': tbil, 'sn': sn_string}
                    st.session_state.keranjang = []
                    st.rerun()

                if st.button("❌ Batal", use_container_width=True):
                    st.session_state.keranjang = []; st.rerun()
            else:
                # Cek jika baru saja transaksi sukses
                if 'last_trx' in st.session_state and st.session_state.last_trx:
                    st.success("✅ Transaksi Berhasil!")
                    st.markdown(f"**ID:** {st.session_state.last_trx['id']}")
                    st.markdown(f"**Total:** {format_rp(st.session_state.last_trx['total'])}")
                    st.markdown("📋 **Copy SN Terjual:**")
                    st.code(st.session_state.last_trx['sn'], language="text")
                    
                    if st.button("Transaksi Baru"):
                        del st.session_state.last_trx
                        st.rerun()
                else:
                    st.info("Keranjang Kosong")

# === GUDANG ===
elif menu == "📦 Gudang":
    st.title("📦 Gudang")
    t1, t2, t3 = st.tabs(["🔍 Cek Stok", "➕ Input", "🛠️ Edit"])
    with t1:
        if not df_master.empty:
            sc, sf = st.columns(2)
            q = sc.text_input("Cari SN/SKU:")
            fb = sf.selectbox("Brand", ["All"] + sorted(df_master['brand'].unique().tolist()))
            dv = df_master.copy()
            if q: dv = dv[dv['sku'].str.contains(q, case=False) | dv['sn'].str.contains(q, case=False)]
            if fb != "All": dv = dv[dv['brand'] == fb]
            st.dataframe(dv[['sn','sku','brand','price','status']], use_container_width=True, hide_index=True)
    with t2:
        if st.session_state.user_role == "ADMIN":
            mode = st.radio("Mode:", ["Manual", "Upload Excel"], horizontal=True)
            if mode == "Manual":
                with st.form("in"):
                    c1,c2,c3 = st.columns(3); b=c1.text_input("Brand"); s=c2.text_input("SKU"); p=c3.number_input("Harga", step=5000)
                    sn = st.text_area("SN (Enter pemisah):")
                    if st.form_submit_button("Simpan", type="primary"):
                        if b and s and sn: 
                            cnt = add_stock_batch(b, s, p, sn.strip().split('\n'))
                            st.success(f"Input {cnt} unit!"); time.sleep(1); st.rerun()
            else:
                uf = st.file_uploader("Excel/CSV", type=['xlsx','csv'])
                if uf and st.button("Import", type="primary"):
                    df = pd.read_csv(uf) if uf.name.endswith('.csv') else pd.read_excel(uf)
                    ok, msg = import_stock_from_df(df)
                    if ok: st.success(msg); time.sleep(2); st.rerun()
                    else: st.error(msg)
    with t3:
        if st.session_state.user_role == "ADMIN":
            if st.text_input("PIN Admin:", type="password") == "123456":
                src = st.text_input("Cari SN Edit:")
                if src and not df_master.empty:
                    de = df_master[df_master['sn'].str.contains(src, case=False)]
                    for i, r in de.iterrows():
                        with st.expander(f"{r['sku']} ({r['sn']})"):
                            np = st.number_input("Harga Baru", value=int(r['price']), key=f"p{r['sn']}")
                            if st.button("Update", key=f"u{r['sn']}"): update_stock_price(r['sn'], np); st.rerun()
                            if st.button("Hapus", key=f"d{r['sn']}", type="primary"): delete_stock(r['sn']); st.rerun()

# === ADMIN TOOLS & LAPORAN ===
elif menu == "🔧 Admin Tools" or menu == "📊 Analitik Bisnis":
    if st.session_state.user_role == "ADMIN":
        st.title("🔧 Dashboard Admin & Tools")
        tab_analitik, tab_tools = st.tabs(["📊 Analitik & Grafik", "💾 Backup & Reset"])
        
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
                st.caption("Download data sebelum melakukan reset!")
                if not df_master.empty:
                    out_stok = io.BytesIO()
                    with pd.ExcelWriter(out_stok, engine='xlsxwriter') as writer:
                        df_master.to_excel(writer, index=False, sheet_name='Stok_Gudang')
                    st.download_button("📥 Download Master Stok (.xlsx)", out_stok.getvalue(), "Backup_Stok.xlsx", "application/vnd.ms-excel", use_container_width=True)
                
                df_hist_all = get_history_df()
                if not df_hist_all.empty:
                    df_clean = df_hist_all.copy()
                    df_clean['waktu_lokal'] = pd.to_datetime(df_clean['timestamp']).dt.tz_convert('Asia/Jakarta')
                    cols_to_save = ['trx_id', 'waktu_lokal', 'user', 'total_bill', 'items_count']
                    out_hist = io.BytesIO()
                    with pd.ExcelWriter(out_hist, engine='xlsxwriter') as writer:
                        df_clean[cols_to_save].to_excel(writer, index=False, sheet_name='Riwayat_Transaksi')
                    st.download_button("📥 Download Riwayat Transaksi (.xlsx)", out_hist.getvalue(), "Backup_Transaksi.xlsx", "application/vnd.ms-excel", use_container_width=True)

            with c_danger:
                st.markdown('<div class="danger-zone">', unsafe_allow_html=True)
                st.markdown("### 2. Danger Zone (Hapus Data)")
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
                                st.success(f"RESET TOTAL BERHASIL! ({c1} Trx, {c2} Stok)")
                            time.sleep(2); st.rerun()
                    else: st.error("PIN SALAH! Akses ditolak.")
                st.markdown('</div>', unsafe_allow_html=True)
    else: st.error("Akses Khusus Admin")
