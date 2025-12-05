# ==========================================
# APLIKASI: SN TRACKER PRO (V2.0 Hybrid)
# ENGINE: Google Firestore (Aman)
# UI/UX: Blibli Gold Style (Keren)
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
if 'confirm_cart' not in st.session_state: st.session_state.confirm_cart = False

# --- 4. CSS CUSTOMIZATION (STYLE BLIBLI) ---
st.markdown("""
    <style>
    :root {
        --blibli-blue: #0095DA;
        --blibli-yellow: #F99D1C;
        --blibli-yellow-hover: #e08e19;
        --text-price: #FF4200;
    }
    .stApp { background-color: #f5f8fa; }
    
    /* Tombol Utama */
    div.stButton > button[kind="primary"] {
        background-color: var(--blibli-blue); border: none; color: white; font-weight: bold;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #007bb5;
    }
    div.stButton > button[kind="secondary"] {
        background-color: white; border: 1px solid var(--blibli-blue); color: var(--blibli-blue);
    }
    
    /* Header Sidebar */
    div[data-testid="stSidebar"] h1 { color: var(--blibli-blue); text-align: center; }
    
    /* Kode SN */
    .stCode { 
        font-size: 18px !important; font-weight: bold; color: var(--blibli-blue); 
        border: 1px solid var(--blibli-blue); background-color: rgba(0, 149, 218, 0.05); border-radius: 6px; 
    }
    
    /* Harga Besar */
    .big-price { font-size: 26px; font-weight: 800; color: var(--text-price); margin-bottom: 10px; display: block; }
    
    /* Header Langkah */
    .step-header { 
        background-color: var(--blibli-blue); color: white; padding: 10px 15px; 
        border-radius: 8px; margin-bottom: 15px; font-weight: 700; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* Alert Stock */
    .alert-stock {
        background-color: #ffebee; color: #c62828; padding: 10px; border-radius: 5px; 
        border: 1px solid #ef9a9a; margin-bottom: 10px; font-weight: bold; font-size: 14px;
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
        'trx_id': trx_id,
        'timestamp': datetime.now(),
        'user': user,
        'items': sn_sold,
        'item_details': cart_items,
        'total_bill': total,
        'items_count': len(sn_sold)
    })
    batch.commit()
    return trx_id, total

def format_rp(val):
    return f"Rp {val:,.0f}".replace(",", ".")

# --- 6. HALAMAN LOGIN (Style Baru) ---
def login_page():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,1.5,1])
    with c2:
        with st.container(border=True):
            st.markdown("<h1 style='text-align: center; margin-bottom:0;'><span style='color: #0095DA;'>BLIBLI</span> <span style='color: #F99D1C;'>POS</span></h1>", unsafe_allow_html=True)
            st.caption("Secure Cloud System v2.0", unsafe_allow_html=True)
            st.markdown("---")
            with st.form("lgn"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("MASUK SISTEM", use_container_width=True, type="primary"):
                    if u == "admin" and p == "admin123":
                        st.session_state.logged_in = True; st.session_state.user_role = "ADMIN"; st.rerun()
                    elif u == "kasir" and p == "blibli2025":
                        st.session_state.logged_in = True; st.session_state.user_role = "KASIR"; st.rerun()
                    else: st.error("Username/Password Salah")

if not st.session_state.logged_in: login_page(); st.stop()

# --- 7. SIDEBAR ---
# Load data awal
df_master = get_inventory_df()

with st.sidebar:
    st.markdown("<h1 style='text-align: center;'>💎 Blibli POS</h1>", unsafe_allow_html=True)
    st.info(f"Halo, **{st.session_state.user_role}**")
    
    if st.button("🚪 Keluar"): 
        st.session_state.logged_in = False
        st.session_state.keranjang = []
        st.rerun()
    st.divider()

    # Alert Stok
    if not df_master.empty:
        stok_ready = df_master[df_master['status'] == 'Ready']
        stok_count = stok_ready.groupby(['brand', 'sku']).size().reset_index(name='jumlah')
        stok_tipis = stok_count[stok_count['jumlah'] < 5]
        if not stok_tipis.empty:
            st.markdown(f"""<div class="alert-stock">🔔 INFO STOK<br>Ada {len(stok_tipis)} item stoknya menipis!</div>""", unsafe_allow_html=True)

    # Menu
    if st.session_state.user_role == "ADMIN":
        menu = st.radio("MENU UTAMA", ["🛒 TRANSAKSI", "📦 GUDANG", "📊 LAPORAN"], index=0)
    else:
        menu = st.radio("MENU UTAMA", ["🛒 TRANSAKSI", "📦 GUDANG"], index=0)
    
    st.divider()
    
    # Info Keranjang di Sidebar
    if st.session_state.keranjang:
        st.warning(f"🛒 {len(st.session_state.keranjang)} Item di Keranjang")
        total_k = sum(item['price'] for item in st.session_state.keranjang)
        st.markdown(f"**Total: {format_rp(total_k)}**")
        if st.button("Hapus Keranjang"):
            st.session_state.keranjang = []
            st.rerun()

# --- 8. KONTEN UTAMA ---

# === FITUR KASIR (Layout Baru) ===
if menu == "🛒 TRANSAKSI":
    c_kiri, c_kanan = st.columns([1.5, 1])
    
    with c_kiri:
        st.markdown('<div class="step-header">1️⃣ CARI BARANG</div>', unsafe_allow_html=True)
        with st.container(border=True):
            if not df_master.empty:
                # Logic Smart Search
                df_ready = df_master[df_master['status'] == 'Ready']
                if not df_ready.empty:
                    # Buat label pencarian yang informatif
                    df_ready['display'] = "[" + df_ready['brand'] + "] " + df_ready['sku'] + " (" + df_ready['price'].apply(format_rp) + ")"
                    
                    # Ambil list unik untuk dropdown
                    search_options = sorted(df_ready['display'].unique())
                    pilih_barang = st.selectbox("🔍 Cari Produk:", ["-- Pilih Produk --"] + search_options)
                    
                    if pilih_barang != "-- Pilih Produk --":
                        # Parse pilihan user untuk dapatkan SKU
                        # Format: [Brand] SKU (Harga)
                        selected_sku = pilih_barang.split("] ")[1].split(" (")[0]
                        
                        # Filter data berdasarkan SKU
                        item_data = df_ready[df_ready['sku'] == selected_sku].iloc[0]
                        st.markdown(f"<span class='big-price'>{format_rp(item_data['price'])}</span>", unsafe_allow_html=True)
                        
                        # Filter SN yang tersedia (exclude yg di keranjang)
                        sn_in_cart = [x['sn'] for x in st.session_state.keranjang]
                        avail_sn = df_ready[(df_ready['sku'] == selected_sku) & (~df_ready['sn'].isin(sn_in_cart))]
                        
                        st.write(f"Stok Tersedia: **{len(avail_sn)} Unit**")
                        
                        if not avail_sn.empty:
                            pilih_sn = st.multiselect("Pilih Serial Number (SN):", avail_sn['sn'].tolist())
                            if st.button("TAMBAH KE KERANJANG ➕", type="primary", use_container_width=True):
                                for sn in pilih_sn:
                                    # Ambil data lengkap item ini
                                    add_item = avail_sn[avail_sn['sn'] == sn].iloc[0].to_dict()
                                    st.session_state.keranjang.append(add_item)
                                st.toast("Barang masuk keranjang!", icon="🛒")
                                time.sleep(0.5)
                                st.rerun()
                        else:
                            st.error("Stok Habis / Semua sudah di keranjang.")
                else: st.warning("Belum ada stok Ready di Gudang.")
            else: st.warning("Database Kosong.")

    with c_kanan:
        st.markdown('<div class="step-header">2️⃣ KERANJANG & CHECKOUT</div>', unsafe_allow_html=True)
        if st.session_state.keranjang:
            with st.container(border=True):
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
                
                st.markdown(f"### Total: {format_rp(total_bayar)}")
                
                if st.button("✅ BAYAR SEKARANG", type="primary", use_container_width=True):
                    trx_id, tot = process_checkout(st.session_state.user_role, st.session_state.keranjang)
                    
                    st.session_state.keranjang = [] # Kosongkan keranjang
                    st.balloons()
                    
                    # Modal Sukses
                    st.success("Transaksi Berhasil!")
                    with st.expander("📄 LIHAT STRUK / COPY SN", expanded=True):
                        st.write(f"**TRX ID:** {trx_id}")
                        st.write(f"**Total:** {format_rp(tot)}")
                        st.code("\n".join([x['sn'] for x in st.session_state.keranjang if 'sn' in x]), language="text")
                        
        else:
            st.info("Keranjang masih kosong.")

# === FITUR GUDANG (Sub-Menu) ===
elif menu == "📦 GUDANG":
    tab1, tab2, tab3 = st.tabs(["🔍 Cek Stok", "➕ Input Barang", "🛠️ Edit/Hapus"])
    
    with tab1:
        st.subheader("Data Stok Gudang")
        if not df_master.empty:
            cari = st.text_input("Filter Pencarian (SN/Nama):")
            df_view = df_master.copy()
            if cari:
                df_view = df_view[df_view['sku'].str.contains(cari, case=False) | df_view['sn'].str.contains(cari, case=False)]
            
            # Warnai status
            def color_status(val):
                return f'background-color: {"#d4edda" if val=="Ready" else "#f8d7da"}'
            
            st.dataframe(
                df_view[['sn', 'sku', 'brand', 'price', 'status']], 
                use_container_width=True,
                column_config={"price": st.column_config.NumberColumn(format="Rp %d")}
            )
        else: st.info("Gudang Kosong")

    with tab2:
        if st.session_state.user_role == "ADMIN":
            st.subheader("Input Stok Baru")
            with st.form("input_new"):
                c1, c2 = st.columns(2)
                ibrand = c1.text_input("Brand")
                isku = c2.text_input("Nama Produk (SKU)")
                iprice = st.number_input("Harga Jual", min_value=0, step=5000)
                isn_text = st.text_area("Scan SN (Pisahkan dengan Enter):", height=100)
                
                if st.form_submit_button("SIMPAN KE DATABASE", type="primary"):
                    if ibrand and isku and isn_text:
                        sn_list = isn_text.strip().split('\n')
                        cnt = add_stock_batch(ibrand, isku, iprice, sn_list)
                        st.success(f"Berhasil input {cnt} unit!")
                        time.sleep(1)
                        st.rerun()
                    else: st.warning("Data belum lengkap!")
        else: st.warning("Akses Input hanya untuk Admin.")

    with tab3:
        if st.session_state.user_role == "ADMIN":
            st.subheader("Edit Data / Hapus Stok")
            st.caption("Cari barang, lalu edit harga atau hapus jika salah input.")
            
            if not df_master.empty:
                cari_edit = st.text_input("Cari SN untuk diedit:")
                if cari_edit:
                    df_edit = df_master[df_master['sn'].str.contains(cari_edit, case=False) | df_master['sku'].str.contains(cari_edit, case=False)]
                    for idx, row in df_edit.iterrows():
                        with st.expander(f"{row['sku']} - {row['sn']}"):
                            c1, c2, c3 = st.columns([2,1,1])
                            new_p = c1.number_input(f"Harga {row['sn']}", value=int(row['price']), key=f"p_{row['sn']}")
                            if c2.button("Update", key=f"up_{row['sn']}"):
                                update_stock_price(row['sn'], new_p)
                                st.toast("Harga Updated!"); time.sleep(1); st.rerun()
                            if c3.button("Hapus", key=f"del_{row['sn']}", type="primary"):
                                delete_stock(row['sn'])
                                st.toast("Data Terhapus!"); time.sleep(1); st.rerun()
            else: st.info("Gudang Kosong")
        else: st.warning("Akses Edit hanya untuk Admin.")

# === FITUR LAPORAN ===
elif menu == "📊 LAPORAN":
    if st.session_state.user_role == "ADMIN":
        st.header("Laporan Penjualan")
        df_hist = get_history_df()
        
        if not df_hist.empty:
            # Convert Timezone
            df_hist['waktu_lokal'] = pd.to_datetime(df_hist['timestamp']).dt.tz_convert('Asia/Jakarta')
            
            # Metrics
            omzet = df_hist['total_bill'].sum()
            trx_count = len(df_hist)
            c1, c2 = st.columns(2)
            c1.metric("Total Omzet", format_rp(omzet))
            c2.metric("Total Transaksi", f"{trx_count}")
            
            # Download Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_export = df_hist[['trx_id', 'waktu_lokal', 'user', 'total_bill', 'items_count']].copy()
                df_export.to_excel(writer, index=False)
            st.download_button("📥 Download Excel Laporan", output.getvalue(), "Laporan_Omzet.xlsx", "application/vnd.ms-excel")
            
            st.dataframe(df_hist[['trx_id', 'waktu_lokal', 'user', 'total_bill']], use_container_width=True)
        else: st.info("Belum ada transaksi.")
    else: st.error("Akses Ditolak.")
