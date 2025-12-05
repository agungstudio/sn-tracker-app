# ==========================================
# APLIKASI: SN TRACKER (Base: Blibli POS Gold)
# VERSI: 1.0 (Firebase Integrated)
# DB ENGINE: Google Cloud Firestore
# ==========================================

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import plotly.express as px
import time

# --- 1. SETUP & KONFIGURASI ---
st.set_page_config(
    page_title="SN Tracker",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. KONEKSI FIREBASE (DATABASE AMAN) ---
@st.cache_resource
def init_db():
    try:
        # Cek apakah aplikasi sudah terkoneksi (supaya tidak init ulang)
        if not firebase_admin._apps:
            # SKENARIO 1: Jalan di Streamlit Cloud (Pake Secrets)
            if 'firestore_key' in st.secrets:
                # Mengambil data dari secrets TOML dan ubah jadi dict
                key_dict = dict(st.secrets['firestore_key'])
                
                # Perbaikan format private_key (kadang error di \n)
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            
            # SKENARIO 2: Jalan di Laptop Lokal (Pake File JSON)
            else:
                cred = credentials.Certificate("firestore_key.json") 
                firebase_admin.initialize_app(cred)
                
        return firestore.client()
    except Exception as e:
        st.error(f"⚠️ Gagal koneksi ke Database: {e}")
        st.stop()

db = init_db()

# --- 3. CUSTOM CSS (TEMA BIRU & KUNING) ---
st.markdown("""
<style>
    /* Warna Utama: Biru Blibli (#0095DA) & Kuning (#F9A01B) */
    .stApp {
        background-color: #f5f7f9;
    }
    .main-header {
        font-size: 2.5rem;
        color: #0095DA;
        font-weight: 800;
        text-align: center;
        margin-bottom: 0px;
    }
    .sub-header {
        color: #F9A01B;
        text-align: center;
        font-weight: 600;
        margin-top: -10px;
        margin-bottom: 30px;
    }
    .stButton>button {
        background-color: #0095DA;
        color: white;
        border-radius: 8px;
        font-weight: bold;
        border: none;
    }
    .stButton>button:hover {
        background-color: #007bb5;
        color: #F9A01B;
    }
    .metric-card {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.05);
        border-left: 5px solid #F9A01B;
    }
    .sn-code {
        font-family: 'Courier New', monospace;
        background-color: #eef;
        padding: 2px 6px;
        border-radius: 4px;
        font-weight: bold;
        color: #0095DA;
    }
</style>
""", unsafe_allow_html=True)

# --- 4. STATE MANAGEMENT ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = None
if 'keranjang' not in st.session_state:
    st.session_state.keranjang = []

# --- 5. FUNGSI LOGIC (BACKEND) ---

def get_inventory_df():
    """Mengambil semua data stok dari Firestore"""
    docs = db.collection('inventory').stream()
    data = []
    for doc in docs:
        d = doc.to_dict()
        d['id'] = doc.id
        data.append(d)
    if not data:
        return pd.DataFrame(columns=['brand', 'sku', 'price', 'sn', 'status', 'created_at'])
    return pd.DataFrame(data)

def get_history_df():
    """Mengambil riwayat transaksi"""
    docs = db.collection('transactions').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
    data = []
    for doc in docs:
        d = doc.to_dict()
        data.append(d)
    if not data:
        return pd.DataFrame(columns=['trx_id', 'timestamp', 'user', 'total', 'items_count'])
    return pd.DataFrame(data)

def add_stock_batch(brand, sku, price, sn_list):
    """Menambah stok banyak sekaligus (Batch Write agar aman)"""
    batch = db.batch()
    count = 0
    for sn in sn_list:
        sn = sn.strip()
        if sn:
            doc_ref = db.collection('inventory').document(sn) # SN jadi ID dokumen (Unik)
            batch.set(doc_ref, {
                'brand': brand,
                'sku': sku,
                'price': int(price),
                'sn': sn,
                'status': 'Ready',
                'created_at': datetime.now()
            })
            count += 1
    batch.commit()
    return count

def process_checkout(user, cart_items):
    """Proses transaksi: Update status stok & catat history"""
    batch = db.batch()
    total_bill = 0
    sn_sold = []
    
    # 1. Update status barang jadi 'Used'
    for item in cart_items:
        doc_ref = db.collection('inventory').document(item['sn'])
        batch.update(doc_ref, {'status': 'Sold'})
        total_bill += item['price']
        sn_sold.append(item['sn'])
    
    # 2. Catat Transaksi
    trx_ref = db.collection('transactions').document()
    batch.set(trx_ref, {
        'trx_id': trx_ref.id,
        'timestamp': datetime.now(),
        'user': user,
        'items': sn_sold,
        'total_bill': total_bill,
        'items_count': len(sn_sold)
    })
    
    batch.commit()
    return total_bill

# --- 6. HALAMAN LOGIN ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<h1 class='main-header'>SN TRACKER</h1>", unsafe_allow_html=True)
        st.markdown("<p class='sub-header'>System Login</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Masuk Sistem", use_container_width=True)
            
            if submit:
                if username == "admin" and password == "admin123":
                    st.session_state.logged_in = True
                    st.session_state.user_role = "ADMIN"
                    st.rerun()
                elif username == "kasir" and password == "blibli2025":
                    st.session_state.logged_in = True
                    st.session_state.user_role = "KASIR"
                    st.rerun()
                else:
                    st.error("Username atau Password salah!")
    st.stop()

# --- 7. APLIKASI UTAMA (SETELAH LOGIN) ---

# Fetch Data Terbaru
df_inventory = get_inventory_df()

# Sidebar Info
st.sidebar.markdown(f"### 👤 Halo, {st.session_state.user_role}")
if st.sidebar.button("Keluar"):
    st.session_state.logged_in = False
    st.session_state.keranjang = []
    st.rerun()

st.sidebar.markdown("---")

# Menu Navigasi
if st.session_state.user_role == "ADMIN":
    menu = st.sidebar.radio("Navigasi", ["Dashboard", "Input Stok", "Data Barang", "Transaksi Kasir"])
else:
    menu = st.sidebar.radio("Navigasi", ["Transaksi Kasir", "Cek Stok"])

# --- HEADER LOGO ---
st.markdown("<h1 class='main-header'>SN TRACKER <span style='color:#F9A01B'>PRO</span></h1>", unsafe_allow_html=True)

# === HALAMAN 1: DASHBOARD (ADMIN) ===
if menu == "Dashboard" and st.session_state.user_role == "ADMIN":
    st.markdown("### 📊 Laporan Kinerja")
    df_hist = get_history_df()
    
    if not df_hist.empty:
        # Metrics
        col1, col2, col3 = st.columns(3)
        omzet = df_hist['total_bill'].sum()
        transaksi = len(df_hist)
        terjual = df_hist['items_count'].sum()
        
        col1.metric("Total Omzet", f"Rp {omzet:,.0f}")
        col2.metric("Total Transaksi", transaksi)
        col3.metric("Unit Terjual", terjual)
        
        # Chart
        df_hist['date'] = pd.to_datetime(df_hist['timestamp']).dt.date
        daily_sales = df_hist.groupby('date')['total_bill'].sum().reset_index()
        fig = px.bar(daily_sales, x='date', y='total_bill', title='Tren Penjualan Harian', color_discrete_sequence=['#0095DA'])
        st.plotly_chart(fig, use_container_width=True)
        
        st.write("Riwayat Transaksi Terakhir:")
        st.dataframe(df_hist.head(10), use_container_width=True)
    else:
        st.info("Belum ada data transaksi.")

# === HALAMAN 2: INPUT STOK (GUDANG/ADMIN) ===
elif menu == "Input Stok" and st.session_state.user_role == "ADMIN":
    st.markdown("### 📦 Input Stok Masuk")
    with st.container(border=True):
        col1, col2 = st.columns(2)
        c_brand = col1.text_input("Brand / Merk")
        c_sku = col2.text_input("Nama Produk / SKU")
        c_price = st.number_input("Harga Jual (Rp)", min_value=0, step=1000)
        
        c_sn_text = st.text_area("Scan/Input Serial Number (SN) - Pisahkan dengan Enter", height=150, help="Satu baris satu SN")
        
        if st.button("💾 Simpan ke Database", use_container_width=True):
            if c_brand and c_sku and c_sn_text:
                sn_list = c_sn_text.strip().split('\n')
                count = add_stock_batch(c_brand, c_sku, c_price, sn_list)
                st.success(f"Berhasil menambahkan {count} unit {c_sku} ke Database!")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Mohon lengkapi semua data!")

# === HALAMAN 3: DATA BARANG & STOK ===
elif menu == "Data Barang" or menu == "Cek Stok":
    st.markdown("### 🔍 Gudang & Stok")
    
    # Filter
    brands = df_inventory['brand'].unique().tolist() if not df_inventory.empty else []
    selected_brand = st.selectbox("Filter Brand", ["Semua"] + brands)
    
    # Tampilkan Data
    if not df_inventory.empty:
        # Filter Logic
        df_view = df_inventory.copy()
        if selected_brand != "Semua":
            df_view = df_view[df_view['brand'] == selected_brand]
        
        # Styling Status
        def highlight_status(val):
            color = '#d4edda' if val == 'Ready' else '#f8d7da' # Green vs Red
            return f'background-color: {color}'

        st.dataframe(
            df_view[['sn', 'brand', 'sku', 'price', 'status']], 
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Gudang kosong.")

# === HALAMAN 4: TRANSAKSI KASIR ===
elif menu == "Transaksi Kasir":
    st.markdown("### 🛒 Kasir Point of Sales")
    
    col_kiri, col_kanan = st.columns([2, 1])
    
    with col_kiri:
        # 1. Pilih Produk (Hanya yang Ready)
        if not df_inventory.empty:
            df_ready = df_inventory[df_inventory['status'] == 'Ready']
            
            # Buat list unik SKU untuk dropdown
            sku_options = df_ready[['sku', 'brand', 'price']].drop_duplicates().to_dict('records')
            sku_map = {f"{item['brand']} - {item['sku']} (Rp {item['price']:,})": item['sku'] for item in sku_options}
            
            pilih_produk = st.selectbox("1. Pilih Produk", ["-- Pilih --"] + list(sku_map.keys()))
            
            # 2. Pilih SN spesifik dari SKU tersebut
            if pilih_produk != "-- Pilih --":
                sku_selected = sku_map[pilih_produk]
                # Filter SN yang ready dan SKU cocok
                sn_options = df_ready[df_ready['sku'] == sku_selected]['sn'].tolist()
                
                # Exclude yang sudah ada di keranjang
                sn_in_cart = [item['sn'] for item in st.session_state.keranjang]
                sn_final = [sn for sn in sn_options if sn not in sn_in_cart]
                
                pilih_sn = st.selectbox("2. Scan/Pilih Serial Number (SN)", ["-- Pilih SN --"] + sn_final)
                
                if st.button("Masuk Keranjang ➕"):
                    if pilih_sn != "-- Pilih SN --":
                        # Ambil detail barang
                        item_data = df_ready[df_ready['sn'] == pilih_sn].iloc[0].to_dict()
                        st.session_state.keranjang.append(item_data)
                        st.success(f"SN {pilih_sn} masuk keranjang")
                        st.rerun()
        else:
            st.warning("Stok Gudang Kosong! Hubungi Admin.")

    with col_kanan:
        st.markdown("#### 🧾 Keranjang Belanja")
        if st.session_state.keranjang:
            total_cart = 0
            for idx, item in enumerate(st.session_state.keranjang):
                st.markdown(f"**{idx+1}. {item['sku']}**")
                st.code(f"{item['sn']}")
                st.markdown(f"Rp {item['price']:,}")
                total_cart += item['price']
                st.divider()
            
            st.markdown(f"### Total: Rp {total_cart:,.0f}")
            
            # Tombol Aksi
            c1, c2 = st.columns(2)
            if c1.button("❌ Batal"):
                st.session_state.keranjang = []
                st.rerun()
            
            if c2.button("✅ Bayar"):
                # Proses Transaksi ke DB
                process_checkout(st.session_state.user_role, st.session_state.keranjang)
                
                # Tampilkan kode untuk copy ke POS lain jika perlu
                sn_list_str = "\n".join([i['sn'] for i in st.session_state.keranjang])
                st.balloons()
                st.success("Transaksi Berhasil Disimpan!")
                st.markdown("Salin SN untuk input ke sistem Blibli Utama:")
                st.code(sn_list_str)
                
                # Reset
                st.session_state.keranjang = []
                time.sleep(5)
                st.rerun()
        else:
            st.info("Keranjang kosong")

# Footer
st.markdown("---")
st.caption("SN Tracker v1.0 | Connected to Google Firestore | Secure Mode")