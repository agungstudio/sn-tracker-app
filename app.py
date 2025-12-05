# ==========================================
# APLIKASI: SN TRACKER PRO (V3.0 Ultimate)
# ENGINE: Google Firestore (Aman)
# UI/UX: Dynamic Dark/Light Mode + Security PIN
# UPDATE: Smart Reset, PIN Protection, Responsive UI
# ==========================================

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import time
import io

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
            # Cek apakah jalan di Cloud (Secrets) atau Lokal (JSON)
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
# Key unik untuk mereset widget input secara otomatis
if 'search_key' not in st.session_state: st.session_state.search_key = 0 

# --- 4. CSS CUSTOMIZATION (DYNAMIC THEME) ---
# Kita menggunakan CSS Variable agar warna menyesuaikan Light/Dark mode otomatis
st.markdown("""
    <style>
    /* VARIAN WARNA BRAND */
    :root {
        --brand-blue: #0095DA;
        --brand-yellow: #F99D1C;
        --brand-accent: #007bb5;
    }
    
    /* MODIFIKASI KOMPONEN NATIVE */
    
    /* Tombol Primary (Biru Blibli) */
    div.stButton > button[kind="primary"] {
        background-color: var(--brand-blue); 
        border: none; 
        color: white; 
        font-weight: bold;
        transition: all 0.3s ease;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: var(--brand-accent);
        transform: scale(1.02);
    }
    
    /* Header Sidebar */
    div[data-testid="stSidebar"] h1 { 
        color: var(--brand-blue); 
        text-align: center;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* Kode SN (Tampilan Chip) */
    .stCode { 
        font-family: 'Courier New', monospace;
        font-weight: bold;
        border-radius: 6px; 
    }
    
    /* Harga Besar */
    .big-price { 
        font-size: 28px; 
        font-weight: 800; 
        color: var(--brand-yellow); 
        margin-bottom: 5px; 
        display: block; 
        text-shadow: 1px 1px 2px rgba(0,0,0,0.1);
    }
    
    /* Header Langkah (Step 1, Step 2) */
    .step-card {
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid var(--brand-blue);
        background-color: rgba(0, 149, 218, 0.05); /* Transparan Biru */
        margin-bottom: 20px;
    }
    
    .step-title {
        color: var(--brand-blue);
        font-weight: 700;
        font-size: 18px;
        margin-bottom: 10px;
    }
    
    /* Alert Stock */
    .alert-stock {
        background-color: rgba(255, 0, 0, 0.1); 
        color: #e53935; 
        padding: 10px; 
        border-radius: 5px; 
        border: 1px solid #ef9a9a; 
        margin-bottom: 10px; 
        font-weight: bold; font-size: 14px;
    }
    
    /* Container Style */
    div[data-testid="stExpander"] {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 8px;
    }
    </style>
""", unsafe_allow_html=True)

# --- 5. FUNGSI LOGIC DATABASE ---
def get_inventory_df():
    """Ambil data stok live"""
    docs = db.collection('inventory').stream()
    data = [{'id': doc.id, **doc.to_dict()} for doc in docs]
    if not data: return pd.DataFrame(columns=['brand', 'sku', 'price', 'sn', 'status'])
    return pd.DataFrame(data)

def get_history_df():
    """Ambil data history transaksi"""
    docs = db.collection('transactions').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
    data = [{'id': doc.id, **doc.to_dict()} for doc in docs]
    if not data: return pd.DataFrame(columns=['trx_id', 'timestamp', 'user', 'total_bill'])
    return pd.DataFrame(data)

def add_stock_batch(brand, sku, price, sn_list):
    """Tambah stok manual (batch kecil)"""
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
    """Import stok massal dari Excel/CSV"""
    df.columns = [c.lower().strip() for c in df.columns]
    required_cols = ['brand', 'sku', 'price', 'sn']
    missing = [c for c in required_cols if c not in df.columns]
    
    if missing:
        return False, f"Format Salah! Kolom hilang: {', '.join(missing)}"
    
    batch = db.batch()
    count = 0
    total_imported = 0
    progress_bar = st.progress(0)
    total_rows = len(df)
    
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
            batch.commit()
            batch = db.batch()
            total_imported += count
            count = 0
            progress_bar.progress(min(index / total_rows, 1.0))
            
    if count > 0:
        batch.commit()
        total_imported += count
        
    progress_bar.progress(1.0)
    time.sleep(0.5)
    progress_bar.empty()
    return True, f"Berhasil mengimport {total_imported} Data Stok!"

def update_stock_price(sn, new_price):
    db.collection('inventory').document(sn).update({'price': int(new_price)})

def delete_stock(sn):
    db.collection('inventory').document(sn).delete()

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
        'user': user, 'items': sn_sold,
        'item_details': cart_items, 'total_bill': total,
        'items_count': len(sn_sold)
    })
    batch.commit()
    return trx_id, total

def format_rp(val):
    return f"Rp {val:,.0f}".replace(",", ".")

# --- 6. HALAMAN LOGIN (Simple & Elegan) ---
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align: center; margin-bottom:0;'><span style='color: #0095DA;'>BLIBLI</span> <span style='color: #F99D1C;'>POS</span></h1>", unsafe_allow_html=True)
            st.caption("v3.0 Secure System", unsafe_allow_html=True)
            st.markdown("---")
            with st.form("lgn"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("LOGIN", use_container_width=True, type="primary"):
                    if u == "admin" and p == "admin123":
                        st.session_state.logged_in = True; st.session_state.user_role = "ADMIN"; st.rerun()
                    elif u == "kasir" and p == "blibli2025":
                        st.session_state.logged_in = True; st.session_state.user_role = "KASIR"; st.rerun()
                    else: st.error("Akses Ditolak")

if not st.session_state.logged_in: login_page(); st.stop()

# --- 7. SIDEBAR ---
# Load data awal (Cache automatically handled by Firestore)
df_master = get_inventory_df()

with st.sidebar:
    st.markdown("### 💎 Blibli POS")
    st.caption(f"User: **{st.session_state.user_role}**")
    
    # Menu Navigasi
    if st.session_state.user_role == "ADMIN":
        menu = st.radio("Navigasi", ["🛒 Transaksi", "📦 Gudang", "📊 Laporan"], label_visibility="collapsed")
    else:
        menu = st.radio("Navigasi", ["🛒 Transaksi", "📦 Gudang"], label_visibility="collapsed")
    
    st.divider()

    # Alert Stok
    if not df_master.empty:
        stok_ready = df_master[df_master['status'] == 'Ready']
        stok_count = stok_ready.groupby(['brand', 'sku']).size().reset_index(name='jumlah')
        stok_tipis = stok_count[stok_count['jumlah'] < 5]
        if not stok_tipis.empty:
            st.markdown(f"""<div class="alert-stock">🔔 INFO STOK<br>Ada {len(stok_tipis)} item stok menipis.</div>""", unsafe_allow_html=True)

    st.markdown("---")
    # Tombol Logout Bawah
    if st.button("🚪 Logout"): 
        st.session_state.logged_in = False
        st.session_state.keranjang = []
        st.rerun()

# --- 8. KONTEN UTAMA ---

# === FITUR KASIR (Smart UI) ===
if menu == "🛒 Transaksi" or menu == "🛒 TRANSAKSI": # Support old/new naming
    st.title("🛒 Kasir")
    
    c_kiri, c_kanan = st.columns([1.6, 1])
    
    with c_kiri:
        st.markdown('<div class="step-card"><div class="step-title">1️⃣ Cari & Scan Barang</div></div>', unsafe_allow_html=True)
        
        if not df_master.empty:
            df_ready = df_master[df_master['status'] == 'Ready']
            if not df_ready.empty:
                df_ready['display'] = "[" + df_ready['brand'] + "] " + df_ready['sku'] + " (" + df_ready['price'].apply(format_rp) + ")"
                search_options = sorted(df_ready['display'].unique())
                
                # Menggunakan key session_state agar bisa di-reset otomatis
                pilih_barang = st.selectbox(
                    "🔍 Ketik Nama Barang / Scan:", 
                    ["-- Pilih Produk --"] + search_options,
                    key=f"search_box_{st.session_state.search_key}" # Key dinamis untuk reset
                )
                
                if pilih_barang != "-- Pilih Produk --":
                    selected_rows = df_ready[df_ready['display'] == pilih_barang]
                    if not selected_rows.empty:
                        item_data = selected_rows.iloc[0]
                        selected_sku = item_data['sku']
                        
                        # Tampilan Harga Besar
                        st.markdown(f"<span class='big-price'>{format_rp(item_data['price'])}</span>", unsafe_allow_html=True)
                        st.caption(f"SKU: {item_data['sku']} | Brand: {item_data['brand']}")
                        
                        # Filter Stok
                        sn_in_cart = [x['sn'] for x in st.session_state.keranjang]
                        avail_sn = df_ready[(df_ready['sku'] == selected_sku) & (~df_ready['sn'].isin(sn_in_cart))]
                        
                        st.markdown("---")
                        c_stok, c_btn = st.columns([2, 1])
                        with c_stok:
                            st.write(f"Stok Tersedia: **{len(avail_sn)} Unit**")
                            if not avail_sn.empty:
                                pilih_sn = st.multiselect("Pilih SN:", avail_sn['sn'].tolist(), label_visibility="collapsed", placeholder="Pilih Serial Number")
                        with c_btn:
                            if not avail_sn.empty:
                                if st.button("➕ TAMBAH", type="primary", use_container_width=True):
                                    if pilih_sn:
                                        for sn in pilih_sn:
                                            add_item = avail_sn[avail_sn['sn'] == sn].iloc[0].to_dict()
                                            st.session_state.keranjang.append(add_item)
                                        
                                        # Reset Box Pencarian agar Kasir bisa langsung scan barang berikutnya
                                        st.session_state.search_key += 1 
                                        st.toast("Masuk Keranjang!", icon="🛒")
                                        time.sleep(0.1)
                                        st.rerun()
                                    else:
                                        st.warning("Pilih SN dulu!")
            else: st.warning("Stok Gudang Kosong.")
        else: st.warning("Database Kosong.")

    with c_kanan:
        st.markdown('<div class="step-card"><div class="step-title">2️⃣ Keranjang Belanja</div></div>', unsafe_allow_html=True)
        
        with st.container(border=True):
            if st.session_state.keranjang:
                total_bayar = 0
                for i, x in enumerate(st.session_state.keranjang):
                    total_bayar += x['price']
                    ca, cb = st.columns([2, 1])
                    with ca:
                        st.markdown(f"**{x['sku']}**")
                        st.caption(f"{x['brand']}")
                    with cb:
                        st.code(x['sn'], language="text")
                    st.divider()
                
                # Summary
                st.markdown(f"<div style='text-align:right'>Total Tagihan<br><span class='big-price'>{format_rp(total_bayar)}</span></div>", unsafe_allow_html=True)
                
                col_pay, col_del = st.columns([3, 1])
                with col_pay:
                    if st.button("✅ BAYAR SEKARANG", type="primary", use_container_width=True):
                        trx_id, tot = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                        st.session_state.keranjang = [] 
                        st.balloons()
                        st.success("Transaksi Berhasil!")
                        with st.expander("📄 LIHAT STRUK / COPY SN", expanded=True):
                            st.write(f"**TRX ID:** {trx_id}")
                            st.write(f"**Total:** {format_rp(tot)}")
                            st.code("\n".join([x['sn'] for x in st.session_state.keranjang if 'sn' in x]), language="text")
                with col_del:
                    if st.button("🗑️", help="Hapus Keranjang"):
                        st.session_state.keranjang = []
                        st.rerun()
            else:
                st.info("Keranjang kosong.")
                st.caption("Pilih barang di sebelah kiri untuk memulai transaksi.")

# === FITUR GUDANG ===
elif menu == "📦 Gudang" or menu == "📦 GUDANG":
    st.title("📦 Manajemen Gudang")
    
    # Tab Navigasi yang lebih bersih
    tab1, tab2, tab3 = st.tabs(["🔍 Cek Stok", "➕ Input Barang", "🛠️ Edit/Hapus"])
    
    with tab1:
        if not df_master.empty:
            c_filter1, c_filter2 = st.columns(2)
            cari = c_filter1.text_input("🔍 Cari Barang (SN / SKU):", placeholder="Ketik sesuatu...")
            filter_brand = c_filter2.selectbox("Filter Brand:", ["Semua"] + sorted(df_master['brand'].unique().tolist()))
            
            df_view = df_master.copy()
            if cari:
                df_view = df_view[df_view['sku'].str.contains(cari, case=False) | df_view['sn'].str.contains(cari, case=False)]
            if filter_brand != "Semua":
                df_view = df_view[df_view['brand'] == filter_brand]
            
            st.dataframe(
                df_view[['sn', 'sku', 'brand', 'price', 'status']], 
                use_container_width=True,
                column_config={
                    "price": st.column_config.NumberColumn("Harga", format="Rp %d"),
                    "sn": "Serial Number",
                    "sku": "Nama Produk"
                },
                hide_index=True
            )
        else: st.info("Gudang Kosong")

    with tab2:
        if st.session_state.user_role == "ADMIN":
            st.info("💡 Pilih metode input data stok.")
            mode_input = st.radio("Metode:", ["Manual / Scan", "Upload Excel"], horizontal=True, label_visibility="collapsed")
            
            if mode_input == "Manual / Scan":
                with st.form("input_new"):
                    c1, c2, c3 = st.columns(3)
                    ibrand = c1.text_input("Brand")
                    isku = c2.text_input("Nama Produk (SKU)")
                    iprice = c3.number_input("Harga Jual", min_value=0, step=5000)
                    isn_text = st.text_area("Scan SN (Pisahkan Enter):", height=100, placeholder="SN001\nSN002\nSN003")
                    
                    if st.form_submit_button("SIMPAN DATA", type="primary", use_container_width=True):
                        if ibrand and isku and isn_text:
                            sn_list = isn_text.strip().split('\n')
                            cnt = add_stock_batch(ibrand, isku, iprice, sn_list)
                            st.success(f"✅ Berhasil input {cnt} unit!")
                            time.sleep(1); st.rerun()
                        else: st.warning("Lengkapi data form.")
            else:
                st.markdown("Download Template: [Template.csv](data:text/csv;base64,Brand,SKU,Price,SN...)")
                uploaded_file = st.file_uploader("Upload File (Excel/CSV)", type=['xlsx', 'csv'])
                if uploaded_file and st.button("🚀 IMPORT SEKARANG", type="primary"):
                    try:
                        df_up = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                        with st.spinner("Mengirim ke Database Cloud..."):
                            suc, msg = import_stock_from_df(df_up)
                            if suc: st.success(msg); time.sleep(2); st.rerun()
                            else: st.error(msg)
                    except Exception as e: st.error(f"Gagal baca file: {e}")

    with tab3:
        if st.session_state.user_role == "ADMIN":
            st.error("🚧 AREA SENSITIF - BUTUH PIN")
            
            pin = st.text_input("Masukkan PIN Admin untuk Edit/Hapus:", type="password")
            if pin == "123456": # GANTI PIN INI JIKA MAU
                st.success("Akses Diberikan")
                cari_edit = st.text_input("Cari SN yang bermasalah:")
                if cari_edit and not df_master.empty:
                    df_edit = df_master[df_master['sn'].str.contains(cari_edit, case=False)]
                    for idx, row in df_edit.iterrows():
                        with st.expander(f"Edit: {row['sku']} ({row['sn']})"):
                            col_ed1, col_ed2 = st.columns(2)
                            new_p = col_ed1.number_input(f"Harga Baru", value=int(row['price']), key=f"p_{row['sn']}")
                            if col_ed1.button("Update Harga", key=f"up_{row['sn']}"):
                                update_stock_price(row['sn'], new_p)
                                st.toast("Harga diperbarui!")
                                time.sleep(1); st.rerun()
                            
                            if col_ed2.button("🗑️ HAPUS PERMANEN", key=f"del_{row['sn']}", type="primary"):
                                delete_stock(row['sn'])
                                st.toast("Data dihapus!"); time.sleep(1); st.rerun()
            elif pin:
                st.error("PIN Salah!")

# === FITUR LAPORAN ===
elif menu == "📊 Laporan" or menu == "📊 LAPORAN":
    if st.session_state.user_role == "ADMIN":
        st.title("📊 Laporan Penjualan")
        df_hist = get_history_df()
        
        if not df_hist.empty:
            df_hist['waktu_lokal'] = pd.to_datetime(df_hist['timestamp']).dt.tz_convert('Asia/Jakarta')
            
            # Kartu Statistik
            omzet = df_hist['total_bill'].sum()
            trx = len(df_hist)
            item_sold = df_hist['items_count'].sum() if 'items_count' in df_hist.columns else 0
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Omzet", format_rp(omzet), "Net")
            m2.metric("Total Transaksi", trx)
            m3.metric("Unit Terjual", item_sold)
            
            st.divider()
            st.subheader("Riwayat Transaksi")
            
            # Export
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_exp = df_hist[['trx_id', 'waktu_lokal', 'user', 'total_bill']].copy()
                df_exp.to_excel(writer, index=False)
            st.download_button("📥 Download Laporan Excel", output.getvalue(), "Laporan_Omzet.xlsx", "application/vnd.ms-excel")
            
            st.dataframe(
                df_hist[['trx_id', 'waktu_lokal', 'user', 'total_bill']], 
                use_container_width=True,
                column_config={
                    "total_bill": st.column_config.NumberColumn("Total", format="Rp %d"),
                    "waktu_lokal": st.column_config.DatetimeColumn("Waktu", format="DD/MM/YY HH:mm")
                }
            )
        else: st.info("Belum ada transaksi.")
    else: st.error("Halaman Khusus Admin.")
