import streamlit as st
import sqlite3
import google.generativeai as genai
import PyPDF2
from docx import Document
import os
import re
import pandas as pd
from datetime import datetime
import math
import io

# --- 1. إعدادات الصفحة والستايل ---

st.set_page_config(page_title="المكتبة الذكية Pro", page_icon="📚", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
html, body, [class*="css"], .stMarkdown, p, h1, h2, h3, h4, li, .stButton, .stSelectbox, .stTextInput, .stMultiSelect {
    font-family: 'Tajawal', sans-serif !important;
    direction: rtl !important; text-align: right !important;
}
.main-card {
    background-color: #ffffff; padding: 20px; border-radius: 12px;
    border-right: 8px solid #0078D4; box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    margin-bottom: 20px; color: #1e1e1e;
}
.index-box {
    background-color: #f8f9fa; padding: 15px; border-radius: 10px;
    border: 1px solid #dee2e6; margin-bottom: 20px;
}
.highlight { color: #d32f2f; font-weight: bold; background-color: #ffeb3b; padding: 0 4px; border-radius: 3px; }
.status-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.85em; background-color: #e1f5fe; color: #01579b; font-weight: bold; }
.page-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.85em; background-color: #fff3cd; color: #856404; font-weight: bold; margin-right: 10px; }
.ai-report { background-color: #f0f4ff; padding: 20px; border-radius: 12px; border: 2px dashed #0078D4; margin-bottom: 20px; color: #1e1e1e; }
.stButton>button { width: 100%; border-radius: 8px; }
.quota-card { background: #fff3cd; padding: 10px; border-radius: 10px; border: 1px solid #ffeeba; font-size: 0.8em; margin-top: 10px; color: #856404; }
.report-header { 
    text-align: center; margin-bottom: 30px; padding: 20px; 
    background: #e3f2fd; border-radius: 10px; border: 1px solid #90caf9;
    color: #1565c0 !important;
}
.report-header h2, .report-header p {
    color: #1565c0 !important;
}
</style>
""", unsafe_allow_html=True)

# --- 2. إدارة الحالة (Session State) ---

if 'api_usage' not in st.session_state: st.session_state['api_usage'] = 0
if 'cat_selector' not in st.session_state: st.session_state['cat_selector'] = "الكل"
if 'current_page' not in st.session_state: st.session_state['current_page'] = 1
if 'scroll_to_id' not in st.session_state: st.session_state['scroll_to_id'] = None
if 'menu_selection' not in st.session_state: st.session_state['menu_selection'] = "🏠 المكتبة"
if 'search_results' not in st.session_state: st.session_state['search_results'] = None
if 'formatted_report' not in st.session_state: st.session_state['formatted_report'] = None
if 'section_ai_summary' not in st.session_state: st.session_state['section_ai_summary'] = None

# --- 3. قاعدة البيانات ---

DB_NAME = 'SmartLibrary_Pro.db'
DEFAULT_CATEGORIES = sorted([
    "إدارة وتخطيط", "الابتكار والإبداع", "الادخار", "الأسرة", "الإعلام والنشر",
    "الذكاء الاصطناعي", "التقنية", "المال", "علمي", "قانونية", "قيادة",
    "تخصصات أخرى", "تربية الأبناء", "مهارية", "نفسي", "البحث العلمي", "التسويق"
])

class DatabaseManager:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        with self.conn:
            self.conn.execute('''CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, raw_text TEXT, file_type TEXT)''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER, category TEXT, summary_text TEXT, date TEXT, FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE)''')
            self.conn.execute('''CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY)''')
            
            count = self.conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
            if count == 0:
                for cat in DEFAULT_CATEGORIES:
                    self.conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))

    def get_categories(self):
        res = self.conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
        return [r[0] for r in res]

    def add_category(self, name):
        try:
            with self.conn:
                self.conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
            return True
        except: return False

    def delete_category(self, name):
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE name=?", (name,))
            self.conn.execute("UPDATE summaries SET category='تخصصات أخرى' WHERE category=?", (name,))

    def bulk_move_category(self, current_cat, target_cat):
        with self.conn:
            self.conn.execute("UPDATE summaries SET category=? WHERE category=?", (target_cat, current_cat))
        st.cache_data.clear()

    def move_multiple_docs(self, doc_ids, target_cat):
        with self.conn:
            placeholders = ','.join('?' for _ in doc_ids)
            query = f"UPDATE summaries SET category=? WHERE id IN ({placeholders})"
            self.conn.execute(query, (target_cat, *doc_ids))
        st.cache_data.clear()

    # --- دوال الحذف الجديدة ---
    def delete_category_content(self, category):
        with self.conn:
            # نحصل على معرفات المستندات في هذا القسم لحذفها من جدول المستندات أيضاً
            rows = self.conn.execute("SELECT document_id FROM summaries WHERE category=?", (category,)).fetchall()
            if rows:
                ids = [r[0] for r in rows]
                placeholders = ','.join('?' for _ in ids)
                # حذف من جدول الملخصات
                self.conn.execute("DELETE FROM summaries WHERE category=?", (category,))
                # حذف من جدول المستندات الأصلية
                self.conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", ids)
        st.cache_data.clear()

    def delete_all_library(self):
        with self.conn:
            self.conn.execute("DELETE FROM summaries")
            self.conn.execute("DELETE FROM documents")
        st.cache_data.clear()
    # -------------------------

    def get_doc_page(self, doc_id, category, page_size=10):
        if category == "الكل":
             count = self.conn.execute("SELECT COUNT(*) FROM summaries WHERE id >= ?", (doc_id,)).fetchone()[0]
        else:
            count = self.conn.execute("SELECT COUNT(*) FROM summaries WHERE category=? AND id >= ?", (category, doc_id)).fetchone()[0]
        
        if count == 0: return 1
        return math.ceil(count / page_size)

    def get_paginated(self, category="الكل", page=1, page_size=10):
        offset = (page - 1) * page_size
        query = "SELECT s.id, d.title, IFNULL(NULLIF(s.category, ''), 'تخصصات أخرى') as category, s.summary_text, s.date FROM summaries s JOIN documents d ON s.document_id = d.id"
        if category != "الكل":
            return pd.read_sql_query(query + " WHERE category=? ORDER BY s.id DESC LIMIT ? OFFSET ?", self.conn, params=(category, page_size, offset))
        return pd.read_sql_query(query + " ORDER BY s.id DESC LIMIT ? OFFSET ?", self.conn, params=(page_size, offset))

    def get_full_text(self, summary_id):
        res = self.conn.execute("SELECT d.raw_text FROM documents d JOIN summaries s ON s.document_id = d.id WHERE s.id=?", (summary_id,)).fetchone()
        return res[0] if res else ""
    
    def get_all_docs_in_category(self, category):
        return pd.read_sql_query("SELECT s.id, d.title FROM summaries s JOIN documents d ON s.document_id = d.id WHERE category=?", self.conn, params=(category,))
    
    def get_category_summaries(self, category):
        res = self.conn.execute("SELECT title, summary_text FROM summaries JOIN documents ON summaries.document_id = documents.id WHERE category=?", (category,)).fetchall()
        return res

    def get_total_count(self, category="الكل"):
        if category == "الكل": return self.conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM summaries WHERE IFNULL(NULLIF(category, ''), 'تخصصات أخرى') = ?", (category,)).fetchone()[0]

    def add_doc(self, title, text, category, summary, ftype="Manual"):
        with self.conn:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO documents (title, raw_text, file_type) VALUES (?, ?, ?)", (title, text, ftype))
            doc_id = cur.lastrowid
            cur.execute("INSERT INTO summaries (document_id, category, summary_text, date) VALUES (?, ?, ?, ?)", (doc_id, category if category else "تخصصات أخرى", summary, datetime.now().strftime("%Y-%m-%d %H:%M")))
        st.cache_data.clear()

    def update_doc(self, summary_id, new_title, new_cat, new_summary, new_raw):
        with self.conn:
            doc_id = self.conn.execute("SELECT document_id FROM summaries WHERE id=?", (summary_id,)).fetchone()[0]
            self.conn.execute("UPDATE documents SET title=?, raw_text=? WHERE id=?", (new_title, new_raw, doc_id))
            self.conn.execute("UPDATE summaries SET category=?, summary_text=? WHERE id=?", (new_cat, new_summary, summary_id))
        st.cache_data.clear()

    def delete_doc(self, summary_id):
        with self.conn:
            doc_id = self.conn.execute("SELECT document_id FROM summaries WHERE id=?", (summary_id,)).fetchone()[0]
            self.conn.execute("DELETE FROM summaries WHERE id=?", (summary_id,))
            self.conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        st.cache_data.clear()

    @st.cache_data(ttl=60)
    def get_lightweight_index(_self):
        return pd.read_sql_query("SELECT s.id, d.title, IFNULL(NULLIF(s.category, ''), 'تخصصات أخرى') as category FROM summaries s JOIN documents d ON s.document_id = d.id ORDER BY s.id DESC", _self.conn)
    
    def get_all_data_for_export(self):
        return pd.read_sql_query("SELECT s.id, d.title, s.category, s.summary_text, s.date FROM summaries s JOIN documents d ON s.document_id = d.id", self.conn)

    def get_stats(self):
        return pd.read_sql_query("SELECT IFNULL(NULLIF(category, ''), 'تخصصات أخرى') as display_category, COUNT(*) as count FROM summaries GROUP BY display_category", self.conn)

db = DatabaseManager(DB_NAME)
CATEGORIES = db.get_categories()

# --- 4. معالج الذكاء الاصطناعي المحسن ---

class AIProcessor:
    @staticmethod
    def get_model(api_keys):
        for key in api_keys:
            if key:
                try:
                    genai.configure(api_key=key)
                    models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    preferred = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-pro']
                    for p in preferred:
                        if p in models: return genai.GenerativeModel(p)
                    if models: return genai.GenerativeModel(models[0])
                except: continue
        return None

    @staticmethod
    def extract_text(file) -> str:
        try:
            ext = file.name.split('.')[-1].lower()
            if ext == 'pdf': return " ".join([p.extract_text() for p in PyPDF2.PdfReader(file).pages if p.extract_text()])
            elif ext == 'docx': return "\n".join([p.text for p in Document(file).paragraphs])
            return file.read().decode('utf-8', errors='ignore')
        except: return ""

    @staticmethod
    def summarize(text, model):
        if not model: return None, None
        st.session_state['api_usage'] += 1
        cats_str = ", ".join(CATEGORIES)
        prompt = f"لخص النص التالي باحترافية (نقاط وفقرات) واختر قسماً واحداً فقط من هذه القائمة: [{cats_str}]. التنسيق: القسم: [اسم القسم] الملخص: [نص التلخيص]. النص: {text[:15000]}"
        try:
            res = model.generate_content(prompt).text
            cat = "تخصصات أخرى"
            for c in CATEGORIES:
                if c in res.split("الملخص:")[0]:
                    cat = c
                    break
            summ = res.split("الملخص:")[-1].strip() if "الملخص:" in res else res
            return cat, summ
        except: return None, None
    
    @staticmethod
    def summarize_section(category, summaries_list, model):
        if not model: return None
        st.session_state['api_usage'] += 1
        context = "\n".join([f"- كتاب/مقال '{t}': {s[:500]}..." for t, s in summaries_list[:30]]) 
        prompt = f"أنت محلل بيانات خبير. لديك مجموعة من الملخصات لمستندات في قسم '{category}'. قم بكتابة تقرير تحليلي شامل يربط بين هذه المواضيع، ويستخرج الاتجاهات العامة، والنقاط المشتركة، وأهم الأفكار المطروحة في هذا القسم.\n\nالمحتوى:\n{context}"
        try:
            return model.generate_content(prompt).text
        except: return "حدث خطأ أثناء التلخيص."

# --- 5. واجهة المستخدم ---

st.sidebar.title("🚀 المكتبة الذكية Pro")
api_keys = [st.sidebar.text_input(f"Gemini API Key {i}:", type="password", key=f"gk_{i}") for i in range(1, 4)]
model = AIProcessor.get_model(api_keys)

if model:
    st.sidebar.success(f"AI نشط: {model.model_name}")
    used = st.session_state['api_usage'] % 15
    st.sidebar.markdown(f'<div class="quota-card">الاستهلاك التقديري: {used}/15 طلب</div>', unsafe_allow_html=True)

menu_options = ["🏠 المكتبة", "📖 الفهرس الشامل", "➕ إضافة مستند", "📂 معالجة مجلد", "🔍 البحث والتحليل", "📊 التقارير والإعدادات"]
st.session_state['menu_selection'] = st.sidebar.selectbox("القائمة الرئيسية", menu_options, index=menu_options.index(st.session_state['menu_selection']))

st.sidebar.markdown("---")
stats = db.get_stats()
for idx, row in stats.iterrows():
    if st.sidebar.button(f"{row['display_category']} ({row['count']})", key=f"stat_btn_{idx}"):
        st.session_state['cat_selector'] = row['display_category']
        st.session_state['current_page'] = 1
        st.session_state['menu_selection'] = "🏠 المكتبة"
        st.rerun()

# --- تنفيذ الصفحات ---

if st.session_state['menu_selection'] == "🏠 المكتبة":
    st.title("📚 مستودع المعرفة")
    all_cats_list = ["الكل"] + CATEGORIES
    current_cat = st.session_state['cat_selector']
    if current_cat not in all_cats_list: current_cat = "الكل"

    c1, c2 = st.columns([2, 1])
    with c1: 
        st.session_state['cat_selector'] = st.selectbox("تصفية حسب القسم", all_cats_list, index=all_cats_list.index(current_cat))
    
    if st.session_state['cat_selector'] != "الكل":
        col_sec_ai_1, col_sec_ai_2 = st.columns(2)
        with col_sec_ai_1:
            if st.button(f"📊 تقرير تحليلي لقسم: {st.session_state['cat_selector']}"):
                if model:
                    with st.spinner('جاري تحليل القسم...'):
                        sec_docs = db.get_category_summaries(st.session_state['cat_selector'])
                        if sec_docs:
                            st.session_state['section_ai_summary'] = AIProcessor.summarize_section(st.session_state['cat_selector'], sec_docs, model)
                        else: st.warning("لا توجد مستندات.")
                else: st.error("الرجاء تفعيل مفتاح API")
        
        with col_sec_ai_2:
            if st.button(f"🔄 تحديث شامل (إعادة تصنيف) للقسم"):
                if model:
                    docs_in_cat = db.get_all_docs_in_category(st.session_state['cat_selector'])
                    if not docs_in_cat.empty:
                        pb = st.progress(0)
                        status_text = st.empty()
                        for i, (idx, row) in enumerate(docs_in_cat.iterrows()):
                            status_text.text(f"جاري معالجة: {row['title']}...")
                            txt = db.get_full_text(row['id'])
                            n_cat, n_summ = AIProcessor.summarize(txt, model)
                            if n_summ:
                                final_cat = n_cat if n_cat in CATEGORIES else st.session_state['cat_selector']
                                db.update_doc(row['id'], row['title'], final_cat, n_summ, txt)
                            pb.progress((i + 1) / len(docs_in_cat))
                        status_text.empty()
                        st.success("تم تحديث القسم وإعادة توزيع المستندات بنجاح!")
                        st.rerun()
                    else: st.warning("القسم فارغ.")
                else: st.error("فعل API Key")

    if st.session_state.get('section_ai_summary') and st.session_state['cat_selector'] != "الكل":
        st.markdown(f'<div class="ai-report"><h3>📊 تقرير القسم: {st.session_state["cat_selector"]}</h3>{st.session_state["section_ai_summary"]}</div>', unsafe_allow_html=True)
        if st.button("إغلاق التقرير"):
            st.session_state['section_ai_summary'] = None
            st.rerun()

    total_items = db.get_total_count(st.session_state['cat_selector'])
    total_pages = max(1, math.ceil(total_items / 10))
    with c2: st.session_state['current_page'] = st.number_input(f"الصفحة (من {total_pages})", 1, total_pages, value=min(st.session_state['current_page'], total_pages))

    df_page = db.get_paginated(st.session_state['cat_selector'], st.session_state['current_page'])

    if not df_page.empty:
        with st.expander("📖 فهرس مواضيع الصفحة الحالية", expanded=True):
            st.markdown('<div class="index-box">', unsafe_allow_html=True)
            for i, row in df_page.iterrows(): st.markdown(f"**{i+1}.** {row['title']} | *({row['category']})*")
            st.markdown('</div>', unsafe_allow_html=True)

        col_group1, col_group2 = st.columns([1, 1])
        with col_group1: expand_all = st.checkbox("🔓 فتح جميع المستندات")
        with col_group2:
            if st.button("🪄 تحديث الصفحة الحالية بالذكاء الاصطناعي"):
                if model:
                    pb = st.progress(0)
                    for i, (idx, row) in enumerate(df_page.iterrows()):
                        txt = db.get_full_text(row['id']); n_cat, n_summ = AIProcessor.summarize(txt, model)
                        if n_cat: db.update_doc(row['id'], row['title'], n_cat, n_summ, txt)
                        pb.progress((i + 1) / len(df_page))
                    st.rerun()
                else: st.error("فعل API Key")

        for _, row in df_page.iterrows():
            is_target = (st.session_state['scroll_to_id'] == row['id'])
            with st.container():
                st.markdown(f'<div class="main-card"><h3>📘 {row["title"]}</h3><p><span class="status-badge">{row["category"]}</span> <span class="status-badge">{row["date"]}</span></p></div>', unsafe_allow_html=True)
                with st.expander("فتح", expanded=(expand_all or is_target)):
                    t1, t2, t3 = st.tabs(["📝 الملخص", "📄 النص الكامل", "✏️ تعديل"])
                    with t1: st.write(row['summary_text'])
                    with t2:
                        if st.button("تحميل النص الكامل", key=f"load_{row['id']}"): st.write(db.get_full_text(row['id']))
                    with t3:
                        new_t = st.text_input("العنوان", row['title'], key=f"edit_t_{row['id']}")
                        cat_index = CATEGORIES.index(row['category']) if row['category'] in CATEGORIES else 0
                        new_c = st.selectbox("القسم", CATEGORIES, index=cat_index, key=f"edit_c_{row['id']}")
                        new_s = st.text_area("الملخص", row['summary_text'], key=f"edit_s_{row['id']}")
                        if st.button("حفظ", key=f"save_{row['id']}"): db.update_doc(row['id'], new_t, new_c, new_s, db.get_full_text(row['id'])); st.rerun()
                cx1, cx2, cx3, _ = st.columns([0.5, 0.5, 0.5, 4])
                if cx1.button("🗑️", key=f"del_{row['id']}"): db.delete_doc(row['id']); st.rerun()
                if cx2.button("📥", key=f"exp_{row['id']}"): st.download_button("تأكيد", db.get_full_text(row['id']), f"{row['title']}.txt")
                if cx3.button("🔄 AI", key=f"ai_{row['id']}"):
                    if model:
                        txt = db.get_full_text(row['id']); n_cat, n_summ = AIProcessor.summarize(txt, model); db.update_doc(row['id'], row['title'], n_cat, n_summ, txt); st.rerun()
                st.divider()
    st.session_state['scroll_to_id'] = None

elif st.session_state['menu_selection'] == "📖 الفهرس الشامل":
    st.title("📖 الفهرس الشامل")
    if st.button("🔄 تحديث بيانات الفهرس"):
        st.cache_data.clear()
        st.rerun()
        
    df_idx = db.get_lightweight_index(); search_idx = st.text_input("🔍 ابحث...")
    filtered_idx = df_idx[df_idx['title'].str.contains(search_idx, case=False)] if search_idx else df_idx
    for _, row in filtered_idx.iterrows():
        c1, c2 = st.columns([5, 1])
        page_num = db.get_doc_page(row['id'], row['category'])
        c1.markdown(f"**{row['title']}** | {row['category']} | <span style='color:#0078D4'>📄 صفحة {page_num}</span>", unsafe_allow_html=True)
        if c2.button("انتقال 🚀", key=f"goto{row['id']}"):
            st.session_state['cat_selector'] = row['category']
            target_page = db.get_doc_page(row['id'], row['category'])
            st.session_state['current_page'] = target_page
            st.session_state['scroll_to_id'] = row['id']
            st.session_state['menu_selection'] = "🏠 المكتبة"
            st.rerun()

elif st.session_state['menu_selection'] == "➕ إضافة مستند":
    st.title("➕ إضافة محتوى")
    with st.form("add_form"):
        t = st.text_input("العنوان"); c_man = st.selectbox("القسم", CATEGORIES); f = st.file_uploader("ملف"); txt = st.text_area("نص")
        if st.form_submit_button("🚀 حفظ"):
            final_txt = AIProcessor.extract_text(f) if f else txt
            if t and final_txt:
                cat, summ = AIProcessor.summarize(final_txt, model) if model else (c_man, final_txt[:300])
                if cat not in CATEGORIES: cat = c_man
                db.add_doc(t, final_txt, cat, summ); st.success("تم!")

elif st.session_state['menu_selection'] == "📂 معالجة مجلد":
    st.title("📂 معالجة مجلدات")
    folder = st.text_input("المسار:");
    if st.button("بدأ"):
        if os.path.isdir(folder):
            files = [f for f in os.listdir(folder) if f.lower().endswith(('.pdf', '.docx', '.txt'))]
            pb = st.progress(0)
            for i, fn in enumerate(files):
                with open(os.path.join(folder, fn), 'rb') as f:
                    content = AIProcessor.extract_text(f); cat, summ = AIProcessor.summarize(content, model); 
                    if cat not in CATEGORIES: cat = "تخصصات أخرى"
                    db.add_doc(fn, content, cat or "تخصصات أخرى", summ or content[:300])
                pb.progress((i+1)/len(files))
            st.success("تم!")

elif st.session_state['menu_selection'] == "🔍 البحث والتحليل":
    st.title("🔍 البحث والتحليل الذكي")
    
    col_search_q, col_search_filter = st.columns([3, 1])
    with col_search_q:
        q = st.text_input("ما الذي تبحث عنه؟")
    with col_search_filter:
        search_filter_cat = st.selectbox("تصفية حسب القسم", ["الكل"] + CATEGORIES)
    
    c1, c2, c3 = st.columns(3)

    if c1.button("🔎 بحث يدوياً"):
        if q:
            sql = "SELECT s.id, d.title, s.category, s.summary_text FROM summaries s JOIN documents d ON s.document_id = d.id WHERE (d.raw_text LIKE ? OR d.title LIKE ?)"
            params = [f"%{q}%", f"%{q}%"]
            if search_filter_cat != "الكل":
                sql += " AND s.category = ?"
                params.append(search_filter_cat)
                
            res = pd.read_sql_query(sql, db.conn, params=tuple(params))
            st.session_state['search_results'] = res; st.session_state['formatted_report'] = None

    if c2.button("🪄 بحث بالذكاء الاصطناعي"):
        if q and model:
            try:
                keywords_resp = model.generate_content(f"استخرج 3 مرادفات عربية أساسية فقط للبحث عن: {q}").text
                keywords = [k.strip() for k in keywords_resp.split()] + [q]
                query_parts = "(" + " OR ".join(["d.raw_text LIKE ?" for _ in keywords]) + ")"
                params = [f"%{k}%" for k in keywords]
                
                sql = f"SELECT s.id, d.title, s.category, s.summary_text FROM summaries s JOIN documents d ON s.document_id = d.id WHERE {query_parts}"
                if search_filter_cat != "الكل":
                    sql += " AND s.category = ?"
                    params.append(search_filter_cat)

                res = pd.read_sql_query(sql, db.conn, params=tuple(params))
                st.session_state['search_results'] = res; st.session_state['formatted_report'] = None
            except: st.error("حدث خطأ في محرك الذكاء الاصطناعي")

    if c3.button("📝 تنسيق النتائج بتقرير AI"):
        if st.session_state['search_results'] is not None and not st.session_state['search_results'].empty:
            if model:
                context = "\n".join([f"- {r['title']}: {r['summary_text']}" for _, r in st.session_state['search_results'].head(5).iterrows()])
                st.session_state['formatted_report'] = model.generate_content(f"لخص النتائج التالية في تقرير مترابط حول '{q}':\n{context}").text
            else: st.error("فعل API Key")

    if st.session_state['formatted_report']:
        st.markdown(f'<div class="ai-report"><h3>📝 الخلاصة</h3>{st.session_state["formatted_report"]}</div>', unsafe_allow_html=True)

    if st.session_state['search_results'] is not None:
        res = st.session_state['search_results']
        if not res.empty:
            st.write(f"النتائج ({len(res)}):")
            for _, r in res.iterrows():
                pattern = re.compile(f"({re.escape(q)})", re.IGNORECASE)
                h_title = pattern.sub(r'<span class="highlight">\1</span>', r['title'])
                
                doc_page = db.get_doc_page(r['id'], r['category'])
                
                st.markdown(f'''
                <div class="main-card">
                    <h4>📌 {h_title}</h4>
                    <p>
                        <span class="status-badge">{r["category"]}</span>
                        <span class="page-badge">صفحة {doc_page}</span>
                    </p>
                    <p>{r["summary_text"]}</p>
                </div>
                ''', unsafe_allow_html=True)
                
                if st.button("انتقال 🚀", key=f"src_{r['id']}"):
                    st.session_state['cat_selector'] = r['category']
                    st.session_state['current_page'] = doc_page
                    st.session_state['scroll_to_id'] = r['id']
                    st.session_state['menu_selection'] = "🏠 المكتبة"
                    st.rerun()
        else: st.warning("لم يتم العثور على نتائج دقيقة.")

elif st.session_state['menu_selection'] == "📊 التقارير والإعدادات":
    st.title("📊 التقارير والإعدادات")
    
    tab1, tab2, tab3 = st.tabs(["⚙️ إدارة الأقسام", "📈 الإحصائيات", "📤 التصدير والطباعة"])
    
    with tab1:
        st.header("إدارة تصنيفات المكتبة")
        
        st.subheader("🔄 نقل المواضيع")
        move_mode = st.radio("نوع النقل", ["نقل قسم بالكامل", "نقل مستندات مختارة"])
        
        if move_mode == "نقل قسم بالكامل":
            col_move1, col_move2, col_move3 = st.columns([2, 2, 1])
            with col_move1: cat_from = st.selectbox("من القسم:", CATEGORIES, key="mv_from")
            with col_move2: cat_to = st.selectbox("إلى القسم:", CATEGORIES, key="mv_to")
            with col_move3:
                st.write("") 
                if st.button("نقل الكل"):
                    if cat_from != cat_to:
                        db.bulk_move_category(cat_from, cat_to)
                        st.success(f"تم نقل المستندات من {cat_from} إلى {cat_to}")
                        st.rerun()
                    else: st.warning("اختر قسمين مختلفين.")
        
        else:
            col_sel1, col_sel2 = st.columns([1, 2])
            with col_sel1:
                src_cat_select = st.selectbox("اختر القسم المصدري:", CATEGORIES, key="multi_src_cat")
            
            with col_sel2:
                search_move = st.text_input("بحث عن موضوع لنقله:", key="search_move_input")

            docs_in_src = db.get_all_docs_in_category(src_cat_select)
            
            if not docs_in_src.empty:
                if search_move:
                    docs_in_src = docs_in_src[docs_in_src['title'].str.contains(search_move, case=False)]

                doc_options = {row['title']: row['id'] for _, row in docs_in_src.iterrows()}
                
                selected_titles = st.multiselect("اختر المستندات لنقلها:", list(doc_options.keys()))
                
                col_btn_move1, col_btn_move2 = st.columns([2, 1])
                with col_btn_move1:
                    target_cat_select = st.selectbox("نقل إلى القسم:", CATEGORIES, key="multi_target_cat")
                with col_btn_move2:
                    st.write("")
                    if st.button("نقل المحدد"):
                        if selected_titles:
                            selected_ids = [doc_options[t] for t in selected_titles]
                            db.move_multiple_docs(selected_ids, target_cat_select)
                            st.success(f"تم نقل {len(selected_ids)} مستند إلى {target_cat_select}")
                            st.rerun()
                        else: st.warning("اختر مستنداً واحداً على الأقل.")
            else:
                st.info("لا توجد مستندات مطابقة في هذا القسم.")

        st.markdown("---")
        
        col_add, col_del = st.columns(2)
        with col_add:
            st.subheader("إضافة قسم جديد")
            new_cat_name = st.text_input("اسم القسم الجديد")
            if st.button("إضافة القسم"):
                if new_cat_name and new_cat_name not in CATEGORIES:
                    if db.add_category(new_cat_name):
                        st.success(f"تم إضافة {new_cat_name}")
                        st.rerun()
                    else: st.error("خطأ في الإضافة")
                elif new_cat_name in CATEGORIES: st.warning("القسم موجود مسبقاً")
        
        with col_del:
            st.subheader("حذف قسم")
            del_cat_name = st.selectbox("اختر القسم لحذفه", CATEGORIES)
            st.warning("⚠️ حذف القسم سينقل مستنداته إلى 'تخصصات أخرى'")
            if st.button("حذف نهائي"):
                db.delete_category(del_cat_name)
                st.success(f"تم حذف {del_cat_name}")
                st.rerun()

        # --- قسم حذف البيانات (الجديد) ---
        st.markdown("---")
        st.subheader("🗑️ منطقة الخطر (حذف البيانات)")
        
        c_del1, c_del2 = st.columns(2)
        with c_del1:
            st.markdown("**حذف محتويات قسم محدد**")
            cat_to_clear = st.selectbox("اختر القسم لتفريغه:", CATEGORIES, key="del_cat_cont_sel")
            confirm_cat_del = st.checkbox(f"أؤكد رغبتي في حذف جميع مستندات '{cat_to_clear}'")
            if st.button("حذف محتويات القسم") and confirm_cat_del:
                db.delete_category_content(cat_to_clear)
                st.success(f"تم تفريغ قسم {cat_to_clear} بنجاح.")
                st.rerun()
        
        with c_del2:
            st.markdown("**حذف كامل المكتبة**")
            st.warning("هذا الإجراء سيحذف جميع المستندات والملخصات نهائياً.")
            confirm_all_del = st.checkbox("أؤكد رغبتي في حذف المكتبة بالكامل")
            if st.button("⚠️ حذف المكتبة بالكامل") and confirm_all_del:
                db.delete_all_library()
                st.success("تم حذف جميع محتويات المكتبة.")
                st.rerun()
        # ---------------------------------

    with tab2:
        st.header("لوحة المعلومات")
        stats_df = db.get_stats()
        if not stats_df.empty:
            c_chart1, c_chart2 = st.columns([2,1])
            with c_chart1:
                st.bar_chart(stats_df.set_index("display_category"))
            with c_chart2:
                st.write("تفصيل الأعداد:")
                st.dataframe(stats_df, hide_index=True)
        else: st.info("لا توجد بيانات كافية.")

    with tab3:
        st.header("تصدير وطباعة البيانات")
        df_export = db.get_all_data_for_export()
        
        try:
            buffer = io.BytesIO()
            try:
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_export.to_excel(writer, sheet_name='Library_Data', index=False)
                btn_excel = st.download_button(
                    label="📥 تحميل التقرير الشامل (Excel)",
                    data=buffer,
                    file_name=f"Library_Report_{datetime.now().date()}.xlsx",
                    mime="application/vnd.ms-excel"
                )
            except Exception as e:
                st.warning("جاري التجهيز بصيغة CSV المتوافقة مع إكسل.")
                csv = df_export.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    label="📥 تحميل التقرير (CSV - Excel Compatible)",
                    data=csv,
                    file_name=f"Library_Report_{datetime.now().date()}.csv",
                    mime="text/csv"
                )
        except MemoryError:
            st.error("⚠️ حجم البيانات كبير جداً على الذاكرة. تم إيقاف التصدير لحماية البرنامج.")
        
        st.markdown("---")
        st.subheader("🖨️ عرض للطباعة")
        if st.button("تجهيز عرض للطباعة"):
            st.markdown(f"""
            <div class='report-header'>
                <h2>تقرير المكتبة الذكية</h2>
                <p>تاريخ التقرير: {datetime.now().strftime("%Y-%m-%d")}</p>
                <p>إجمالي المستندات: {len(df_export)}</p>
            </div>
            """, unsafe_allow_html=True)
            
            df_print = df_export.copy()
            df_print['category'] = df_print['category'].fillna("تخصصات أخرى")
            df_print.sort_values(by=['category', 'id'], ascending=[True, False], inplace=True)
            df_print['rank'] = df_print.groupby('category').cumcount() + 1
            df_print['rank'] = df_print['rank'].fillna(1)
            df_print['page_number'] = df_print['rank'].apply(lambda x: math.ceil(x / 10))
            
            df_print.rename(columns={'title': 'العنوان', 'category': 'القسم', 'summary_text': 'الملخص', 'date': 'التاريخ', 'page_number': 'رقم الصفحة'}, inplace=True)
            
            st.dataframe(df_print[['العنوان', 'القسم', 'رقم الصفحة', 'الملخص', 'التاريخ']], use_container_width=True)
            st.caption("يمكنك استخدام خيار الطباعة من المتصفح (Ctrl+P) لطباعة هذا الجدول.")