# ==========================================
# APLIKASI: SN TRACKER PRO (V4.8 Search-First)
# ENGINE: Google Firestore
# FIX: Mode "Hemat Kuota Ekstrem".
# Menghapus "Load All Data" di awal. Menggunakan logika
# Search-by-Query untuk mengurangi pembacaan dokumen.
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
if 'last_trx' not in st.session_state: st.session_state.last_trx = {}
if 'confirm_logout' not in st.session_state: st.session_state.confirm_logout = False
# State khusus untuk hasil pencarian agar tidak hilang saat reload
if 'search_result' not in st.session_state: st.session_state.search_result = None

# --- 4. CSS CUSTOMIZATION ---
st.markdown("""
    <style>
    :root {
        --brand-blue: #0095DA;
        --brand-yellow: #F99D1C;
    }
    div.stButton > button[kind="primary"] {
        background-color: var(--brand-blue); border: none; color: white; font-weight: bold;
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
    div[data-testid="stVerticalBlock"] .stCode {
        margin-bottom: 0px !important;
    }
    .metric-card {
        background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #0095DA;
    }
    .danger-zone {
        border: 2px solid #e53935; background-color: #ffebee; padding: 20px; border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 5. FUNGSI LOGIC (HEMAT KUOTA) ---

def format_rp(val): return f"Rp {val:,.0f}".replace(",", ".")

# HANYA DIGUNAKAN UNTUK DASHBOARD (DIBATASI TANGGAL)
@st.cache_data(ttl=600)
def get_recent_history(days=7):
    """Hanya ambil transaksi X hari terakhir untuk hemat kuota"""
    cutoff = datetime.now() - timedelta(days=days)
    docs = db.collection('transactions').where('timestamp', '>=', cutoff).order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
    data = [{'id': doc.id, **doc.to_dict()} for doc in docs]
    if not data: return pd.DataFrame(columns=['trx_id', 'timestamp', 'user', 'total_bill'])
    return pd.DataFrame(data)

# FUNGSI CARI SPESIFIK (SUPER HEMAT - 1 Read per Search)
def search_item_by_sn(sn_query):
    """Cari barang berdasarkan SN exact match"""
    sn_query = sn_query.strip()
    doc_ref = db.collection('inventory').document(sn_query)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id
        # Cek status
        if data.get('status') != 'Ready':
            return None, "Barang sudah terjual / tidak ready."
        return data, "OK"
    else:
        return None, "SN tidak ditemukan."

def search_item_by_keyword(keyword):
    """
    Cari barang berdasarkan Brand atau SKU.
    WARNING: Firestore tidak support 'contains'. Kita pakai '==' atau manual filter di client (mahal).
    Solusi Hemat: Kita pakai 'where' exact match untuk Brand, atau SKU.
    """
    # Mencari berdasarkan Brand
    results = []
    
    # 1. Coba cari sebagai Brand
    docs_brand = db.collection('inventory').where('brand', '==', keyword).where('status', '==', 'Ready').limit(20).stream()
    for doc in docs_brand:
        d = doc.to_dict()
        d['id'] = doc.id
        results.append(d)
        
    # 2. Jika kosong, coba cari SKU (Harus Exact di Firestore Free)
    if not results:
        docs_sku = db.collection('inventory').where('sku', '==', keyword).where('status', '==', 'Ready').limit(20).stream()
        for doc in docs_sku:
            d = doc.to_dict()
            d['id'] = doc.id
            results.append(d)
            
    return results

def log_import_activity(user, method, count):
    db.collection('import_logs').add({
        'timestamp': datetime.now(), 'user': user,
        'method': method, 'total_items': count
    })

def add_stock_batch(user, brand, sku, price, sn_list):
    batch = db.batch(); count = 0; total_added = 0
    for sn in sn_list:
        sn = sn.strip()
        if sn:
            doc_ref = db.collection('inventory').document(sn)
            batch.set(doc_ref, {'brand': brand, 'sku': sku, 'price': int(price), 'sn': sn, 'status': 'Ready', 'created_at': datetime.now()})
            count += 1
            if count >= 400: batch.commit(); batch = db.batch(); total_added += count; count = 0
    if count > 0: batch.commit(); total_added += count
    if total_added > 0: log_import_activity(user, "Manual Input", total_added)
    return total_added

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
if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align:center; color:#0095DA;'>SN <span style='color:#F99D1C;'>TRACKER</span></h1>", unsafe_allow_html=True)
            st.caption("v4.8 Search-First (Hemat Kuota)", unsafe_allow_html=True)
            with st.form("lgn"):
                u = st.text_input("Username"); p = st.text_input("Password", type="password")
                if st.form_submit_button("LOGIN", use_container_width=True, type="primary"):
                    if u == "admin" and p == "admin123":
                        st.session_state.logged_in = True; st.session_state.user_role = "ADMIN"; st.rerun()
                    elif u == "kasir" and p == "blibli2025":
                        st.session_state.logged_in = True; st.session_state.user_role = "KASIR"; st.rerun()
                    else: st.error("Akses Ditolak")
    st.stop()

# --- 7. SIDEBAR (TANPA LOAD ALL DATA) ---
with st.sidebar:
    st.markdown("### 📦 SN Tracker")
    st.markdown(f"User: **{st.session_state.user_role}**")
    menu = st.radio("Menu Utama", ["🛒 Kasir", "📦 Gudang", "🔧 Admin Tools"] if st.session_state.user_role == "ADMIN" else ["🛒 Kasir", "📦 Gudang"], label_visibility="collapsed")
    st.divider()
    
    # INFO STOK DIHILANGKAN DARI SIDEBAR UTK HEMAT KUOTA
    # Hanya tampilkan tombol logout
    
    st.markdown("<br>" * 5, unsafe_allow_html=True) 
    if st.session_state.confirm_logout:
        st.warning("Keluar?")
        c1, c2 = st.columns(2)
        if c1.button("YA", use_container_width=True):
            st.session_state.logged_in = False; st.session_state.keranjang = []; st.session_state.confirm_logout = False; st.rerun()
        if c2.button("BATAL", use_container_width=True):
            st.session_state.confirm_logout = False; st.rerun()
    else:
        if st.button("🚪 KELUAR", use_container_width=True): st.session_state.confirm_logout = True; st.rerun()

# --- 8. KONTEN UTAMA ---

# === KASIR ===
if menu == "🛒 Kasir":
    st.title("🛒 Kasir Point of Sales")
    c_product, c_cart = st.columns([1.8, 1])
    
    with c_product:
        st.markdown('<div class="step-header">1️⃣ Scan / Cari Barang</div>', unsafe_allow_html=True)
        st.info("💡 Ketik Serial Number (SN) persis untuk hasil tercepat.")
        
        # SEARCH BAR SINGLE INPUT (HEMAT KUOTA)
        search_query = st.text_input("Scan Barcode / Ketik SN:", key="sn_search_input", placeholder="Contoh: SN12345")
        
        if st.button("🔍 CARI BARANG", type="primary", use_container_width=True) or search_query:
            if search_query:
                # 1. Coba Cari by SN (1 Read)
                item, msg = search_item_by_sn(search_query)
                
                if item:
                    # TAMPILAN JIKA KETEMU
                    st.success("✅ Barang Ditemukan!")
                    with st.container(border=True):
                        c_img, c_det = st.columns([1, 3])
                        with c_det:
                            st.markdown(f"### {item['sku']}")
                            st.caption(f"Brand: {item['brand']} | SN: {item['sn']}")
                            st.markdown(f"<span class='big-price'>{format_rp(item['price'])}</span>", unsafe_allow_html=True)
                            
                            # Cek keranjang
                            in_cart = any(x['sn'] == item['sn'] for x in st.session_state.keranjang)
                            
                            if in_cart:
                                st.warning("⚠️ Barang sudah di keranjang")
                            else:
                                if st.button("TAMBAH KE KERANJANG ➕", key=f"add_{item['sn']}"):
                                    st.session_state.keranjang.append(item)
                                    st.toast("Masuk Keranjang!", icon="🛒")
                                    time.sleep(0.5)
                                    st.rerun()
                else:
                    st.error(f"❌ {msg}")
                    st.caption("Tips: Pastikan SN diketik persis sama (Huruf Besar/Kecil berpengaruh).")

    with c_cart:
        st.markdown('<div class="step-header">2️⃣ Keranjang</div>', unsafe_allow_html=True)
        if st.session_state.keranjang:
            with st.container(height=400, border=True):
                st.caption(f"{len(st.session_state.keranjang)} Item")
                for item in st.session_state.keranjang:
                    st.markdown(f"**{item['sku']}**")
                    c1, c2 = st.columns([2.5, 1])
                    c1.code(item['sn'], language="text")
                    c2.markdown(f"<div style='text-align:right;font-weight:bold'>{format_rp(item['price'])}</div>", unsafe_allow_html=True)
                    st.divider()
            
            with st.container(border=True):
                tot = sum(i['price'] for i in st.session_state.keranjang)
                st.markdown(f"<div style='text-align:right'>Total: <span class='big-price'>{format_rp(tot)}</span></div>", unsafe_allow_html=True)
                if st.button("✅ BAYAR SEKARANG", type="primary", use_container_width=True):
                    tid, tbil = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                    st.session_state.keranjang = []; st.session_state.last_trx = {'id': tid, 'total': tbil}
                    st.balloons(); st.rerun()
                if st.button("❌ Batal"): st.session_state.keranjang = []; st.rerun()
        else:
            if st.session_state.last_trx:
                st.success("Transaksi Sukses!")
                st.write(f"ID: {st.session_state.last_trx['id']}")
                st.write(f"Total: {format_rp(st.session_state.last_trx['total'])}")
                if st.button("Tutup"): st.session_state.last_trx = {}; st.rerun()
            else: st.info("Keranjang Kosong")

# === GUDANG (Mode Hemat) ===
elif menu == "📦 Gudang":
    st.title("📦 Manajemen Gudang")
    t1, t2 = st.tabs(["🔍 Cari Stok", "➕ Input Barang"])
    
    with t1:
        st.info("💡 Mode Hemat Kuota: Masukkan kata kunci untuk melihat stok.")
        keyword = st.text_input("Cari Brand / SKU (Persis):", placeholder="Contoh: Samsung")
        
        if st.button("🔎 CARI DATA"):
            if keyword:
                results = search_item_by_keyword(keyword)
                if results:
                    st.success(f"Ditemukan {len(results)} barang.")
                    df_res = pd.DataFrame(results)
                    st.dataframe(df_res[['sn', 'sku', 'brand', 'price', 'status']], use_container_width=True)
                else:
                    st.warning("Tidak ditemukan barang dengan Brand/SKU persis tersebut.")
            else:
                st.warning("Ketik kata kunci dulu.")

    with t2:
        if st.session_state.user_role == "ADMIN":
            st.subheader("Input Stok")
            with st.form("in"):
                c1,c2,c3 = st.columns(3); b=c1.text_input("Brand"); s=c2.text_input("SKU"); p=c3.number_input("Harga", step=5000)
                sn = st.text_area("List SN (Enter pemisah):"); 
                if st.form_submit_button("SIMPAN", type="primary"):
                    if b and s and sn: 
                        add_stock_batch(st.session_state.user_role, b, s, p, sn.strip().split('\n'))
                        st.success("Tersimpan!"); time.sleep(1); st.rerun()
        else: st.error("Khusus Admin")

# === ADMIN ===
elif menu == "🔧 Admin Tools":
    if st.session_state.user_role == "ADMIN":
        st.title("🔧 Admin Tools")
        st.info("Dashboard hanya menampilkan data 7 hari terakhir untuk hemat kuota.")
        
        df_hist = get_recent_history(7) # Cuma ambil 7 hari terakhir
        if not df_hist.empty:
            m1, m2 = st.columns(2)
            m1.metric("Omzet (7 Hari)", format_rp(df_hist['total_bill'].sum()))
            m2.metric("Transaksi (7 Hari)", len(df_hist))
            st.dataframe(df_hist, use_container_width=True)
        else:
            st.info("Tidak ada transaksi dalam 7 hari terakhir.")
            
        st.markdown("---")
        if st.button("HAPUS CACHE APLIKASI"):
            st.cache_data.clear()
            st.success("Cache berhasil dihapus.")
    else: st.error("Khusus Admin")
