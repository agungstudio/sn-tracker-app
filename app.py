# ==========================================
# APLIKASI: SN TRACKER (Base: Blibli POS Gold)
# VERSI: 1.1 (Fitur Edit, Hapus, Download Excel)
# ==========================================

import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import plotly.express as px
import time
import io

# --- 1. SETUP & KONFIGURASI ---
st.set_page_config(
    page_title="SN Tracker Pro",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. KONEKSI FIREBASE (SMART CONNECT) ---
@st.cache_resource
def init_db():
    try:
        if not firebase_admin._apps:
            # SKENARIO 1: Streamlit Cloud (Secrets)
            if 'firestore_key' in st.secrets:
                key_dict = dict(st.secrets['firestore_key'])
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            # SKENARIO 2: Laptop Lokal (JSON File)
            else:
                cred = credentials.Certificate("firestore_key.json") 
                firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"⚠️ Gagal koneksi Database: {e}")
        st.stop()

db = init_db()

# --- 3. CUSTOM CSS ---
st.markdown("""
<style>
    .stApp { background-color: #f0f2f6; }
    .main-header { color: #0095DA; font-weight: 800; text-align: center; margin: 0; }
    .sub-header { color: #F9A01B; text-align: center; font-weight: 600; margin-bottom: 20px; }
    .stButton>button { background-color: #0095DA; color: white; border-radius: 8px; border: none; }
    .stButton>button:hover { background-color: #007bb5; color: #F9A01B; }
    .status-ready { color: #28a745; font-weight: bold; }
    .status-sold { color: #dc3545; font-weight: bold; }
    div[data-testid="stExpander"] { border: 1px solid #ddd; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# --- 4. STATE MANAGEMENT ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'keranjang' not in st.session_state: st.session_state.keranjang = []

# --- 5. FUNGSI LOGIC (CRUD) ---

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

def update_stock_price(sn, new_price):
    """Update harga barang"""
    db.collection('inventory').document(sn).update({'price': int(new_price)})

def delete_stock(sn):
    """Hapus barang permanen"""
    db.collection('inventory').document(sn).delete()

def process_checkout(user, cart_items):
    batch = db.batch()
    total = sum(item['price'] for item in cart_items)
    sn_sold = [item['sn'] for item in cart_items]
    
    # 1. Update Inventory jadi Sold
    for item in cart_items:
        doc_ref = db.collection('inventory').document(item['sn'])
        batch.update(doc_ref, {'status': 'Sold', 'sold_at': datetime.now()})
    
    # 2. Catat Transaksi
    trx_ref = db.collection('transactions').document()
    trx_id = trx_ref.id[:8].upper() # ID pendek
    batch.set(trx_ref, {
        'trx_id': trx_id,
        'timestamp': datetime.now(),
        'user': user,
        'items': sn_sold,
        'item_details': cart_items, # Simpan detail lengkap untuk report
        'total_bill': total,
        'items_count': len(sn_sold)
    })
    batch.commit()
    return trx_id, total

# --- 6. HALAMAN LOGIN ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("<h1 class='main-header'>SN TRACKER</h1>", unsafe_allow_html=True)
        st.markdown("<p class='sub-header'>System Login</p>", unsafe_allow_html=True)
        with st.form("login_form"):
            user = st.text_input("Username")
            pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Masuk", use_container_width=True):
                if user == "admin" and pwd == "admin123":
                    st.session_state.logged_in = True
                    st.session_state.user_role = "ADMIN"
                    st.rerun()
                elif user == "kasir" and pwd == "blibli2025":
                    st.session_state.logged_in = True
                    st.session_state.user_role = "KASIR"
                    st.rerun()
                else: st.error("Login Gagal")
    st.stop()

# --- 7. DASHBOARD UTAMA ---
df_inv = get_inventory_df()

# Sidebar
st.sidebar.title(f"👤 {st.session_state.user_role}")
menu_options = ["Dashboard", "Input Stok", "Manajemen Stok"] if st.session_state.user_role == "ADMIN" else ["Transaksi Kasir", "Cek Stok"]
menu = st.sidebar.radio("Menu", menu_options)
if st.sidebar.button("Logout"):
    st.session_state.logged_in = False
    st.session_state.keranjang = []
    st.rerun()

# Content
st.markdown(f"## {menu}")

# === DASHBOARD (Laporan) ===
if menu == "Dashboard":
    df_hist = get_history_df()
    if not df_hist.empty:
        # Konversi waktu ke WIB (UTC+7)
        # PERBAIKAN: Hapus .dt.tz_localize('UTC') karena data Firestore sudah timezone-aware
        df_hist['waktu_lokal'] = pd.to_datetime(df_hist['timestamp']).dt.tz_convert('Asia/Jakarta')
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Omzet", f"Rp {df_hist['total_bill'].sum():,.0f}")
        c2.metric("Total Transaksi", len(df_hist))
        c3.metric("Stok Ready", len(df_inv[df_inv['status']=='Ready']) if not df_inv.empty else 0)
        
        # Download Excel
        st.subheader("📥 Riwayat Transaksi")
        
        # Tombol Download
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export = df_hist[['trx_id', 'waktu_lokal', 'user', 'total_bill', 'items_count']].copy()
            df_export.to_excel(writer, index=False, sheet_name='Sheet1')
        st.download_button(label="Download Laporan Excel", data=output.getvalue(), file_name="Laporan_Penjualan.xlsx", mime="application/vnd.ms-excel")

        st.dataframe(df_hist[['trx_id', 'waktu_lokal', 'user', 'total_bill', 'items']], use_container_width=True)
    else:
        st.info("Belum ada data transaksi.")

# === INPUT STOK (Admin) ===
elif menu == "Input Stok":
    with st.form("input_stok"):
        c1, c2 = st.columns(2)
        brand = c1.text_input("Brand (Merk)")
        sku = c2.text_input("Tipe/Nama Produk")
        price = st.number_input("Harga Jual", min_value=0, step=5000)
        sn_text = st.text_area("Scan SN (Satu baris satu SN)", height=100)
        if st.form_submit_button("Simpan Data"):
            if brand and sku and sn_text:
                sn_list = sn_text.strip().split('\n')
                count = add_stock_batch(brand, sku, price, sn_list)
                st.success(f"Sukses input {count} unit!")
                time.sleep(1)
                st.rerun()
            else: st.warning("Lengkapi data!")

# === MANAJEMEN STOK (Edit/Hapus) ===
elif menu == "Manajemen Stok":
    st.info("💡 Klik checkbox di kiri untuk Edit/Hapus barang.")
    if not df_inv.empty:
        # Filter Pencarian
        search = st.text_input("Cari SN / Nama Produk", placeholder="Ketik SN atau nama...")
        
        df_show = df_inv.copy()
        if search:
            df_show = df_show[df_show['sku'].str.contains(search, case=False) | df_show['sn'].str.contains(search, case=False)]
        
        # Tampilan Data Editor
        for index, row in df_show.iterrows():
            with st.expander(f"{row['sn']} - {row['sku']} ({row['status']})"):
                c1, c2, c3 = st.columns([2,1,1])
                new_price = c1.number_input(f"Harga {row['sn']}", value=int(row['price']), key=f"p_{row['sn']}")
                
                if c2.button("Update Harga", key=f"up_{row['sn']}"):
                    update_stock_price(row['sn'], new_price)
                    st.success("Harga diupdate!")
                    time.sleep(0.5); st.rerun()
                
                if c3.button("HAPUS DATA", key=f"del_{row['sn']}", type="primary"):
                    delete_stock(row['sn'])
                    st.warning("Data dihapus permanen.")
                    time.sleep(0.5); st.rerun()
    else:
        st.write("Gudang Kosong.")

# === TRANSAKSI KASIR ===
elif menu == "Transaksi Kasir":
    c_left, c_right = st.columns([2,1])
    
    with c_left:
        st.subheader("Pilih Barang")
        if not df_inv.empty:
            df_ready = df_inv[df_inv['status'] == 'Ready']
            sku_list = df_ready['sku'].unique().tolist()
            pilih_sku = st.selectbox("Cari Produk", ["--Pilih--"] + sku_list)
            
            if pilih_sku != "--Pilih--":
                # Filter SN berdasarkan SKU
                avail_sn = df_ready[df_ready['sku'] == pilih_sku]
                # Filter yang belum masuk keranjang
                cart_sn = [x['sn'] for x in st.session_state.keranjang]
                avail_sn = avail_sn[~avail_sn['sn'].isin(cart_sn)]
                
                pilih_sn = st.selectbox("Pilih Serial Number (SN)", ["--Pilih--"] + avail_sn['sn'].tolist())
                
                if st.button("Tambah ke Keranjang"):
                    if pilih_sn != "--Pilih--":
                        item = avail_sn[avail_sn['sn'] == pilih_sn].iloc[0].to_dict()
                        st.session_state.keranjang.append(item)
                        st.rerun()
        else: st.error("Stok Habis!")

    with c_right:
        st.subheader("🧾 Keranjang")
        if st.session_state.keranjang:
            total = 0
            for i, item in enumerate(st.session_state.keranjang):
                st.text(f"{item['sku']}\nSN: {item['sn']}")
                st.markdown(f"**Rp {item['price']:,}**")
                total += item['price']
                st.divider()
            
            st.markdown(f"### Total: Rp {total:,.0f}")
            
            if st.button("BAYAR SEKARANG", type="primary", use_container_width=True):
                trx_id, tot_bill = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                
                # TAMPILAN STRUK DIGITAL
                st.success("Transaksi Berhasil!")
                struk_text = f"""
                === BLIBLI POS GOLD ===
                ID Trx   : {trx_id}
                Tanggal  : {datetime.now().strftime('%d-%m-%Y %H:%M')}
                Kasir    : {st.session_state.user_role}
                -----------------------
                """
                for item in st.session_state.keranjang:
                    struk_text += f"\n{item['sku']}\nSN: {item['sn']}\nRp {item['price']:,}\n"
                struk_text += f"\n-----------------------\nTOTAL    : Rp {tot_bill:,}\nTerima Kasih!"
                
                st.text_area("Salin Struk Digital", value=struk_text, height=200)
                
                st.session_state.keranjang = [] # Reset

            if st.button("Hapus Keranjang"):
                st.session_state.keranjang = []
                st.rerun()

# === CEK STOK (View Only) ===
elif menu == "Cek Stok":
    st.subheader("Daftar Stok Gudang")
    if not df_inv.empty:
        search = st.text_input("Cari Barang...")
        df_view = df_inv.copy()
        if search:
            df_view = df_view[df_view['sku'].str.contains(search, case=False) | df_view['sn'].str.contains(search, case=False)]
        st.dataframe(df_view[['sn', 'sku', 'brand', 'price', 'status']], use_container_width=True)
