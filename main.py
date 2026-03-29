import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
import pandas as pd
from datetime import datetime
import math
import io
import re
from streamlit_gsheets import GSheetsConnection

# --- 1. إعدادات الصفحة والستايل الاحترافي (نفس الأصلي) ---
st.set_page_config(page_title="المكتبة الذكية Pro - سحابية", page_icon="📚", layout="wide")

st.markdown("""
<style>
@import url('https://docs.google.com/spreadsheets/d/1175I-7_jtI8Qt4GdC7CUuHaZTGI8u82s/edit?usp=sharing&ouid=101710061388629504590&rtpof=true&sd=true');
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
.ai-report { background-color: #f0f4ff; padding: 20px; border-radius: 12px; border: 2px dashed #0078D4; margin-bottom: 20px; color: #1e1e1e; }
.quota-card { background: #fff3cd; padding: 10px; border-radius: 10px; border: 1px solid #ffeeba; font-size: 0.8em; margin-top: 10px; color: #856404; }
</style>
""", unsafe_allow_html=True)

# --- 2. إدارة البيانات عبر Google Sheets ---
# استبدل هذا الرابط برابط جدولك
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1ERRHdDEHDGqhIpa_x5T3pUDXEYXfGC8y7ysMCrYQ15k/edit?usp=sharing"

conn = st.connection("gsheets", type=GSheetsConnection)

def load_full_data():
    try:
        df = conn.read(spreadsheet=SPREADSHEET_URL, ttl=0)
        # التأكد من وجود الأعمدة المطلوبة
        required = ["id", "title", "category", "summary_text", "raw_text", "date"]
        for col in required:
            if col not in df.columns: df[col] = ""
        return df
    except:
        return pd.DataFrame(columns=["id", "title", "category", "summary_text", "raw_text", "date"])

def save_full_data(df):
    conn.update(spreadsheet=SPREADSHEET_URL, data=df)
    st.cache_data.clear()

# --- 3. إدارة الحالة (Session State) ---
if 'api_usage' not in st.session_state: st.session_state['api_usage'] = 0
if 'menu_selection' not in st.session_state: st.session_state['menu_selection'] = "🏠 المكتبة"
if 'cat_selector' not in st.session_state: st.session_state['cat_selector'] = "الكل"

CATEGORIES = sorted(["إدارة وتخطيط", "الابتكار والإبداع", "الادخار", "الأسرة", "الذكاء الاصطناعي", "التقنية", "المال", "علمي", "قانونية", "قيادة", "تخصصات أخرى", "تربية الأبناء", "مهارية", "نفسي", "البحث العلمي", "التسويق"])

# --- 4. معالج الذكاء الاصطناعي (نفس الأصلي) ---
class AIProcessor:
    @staticmethod
    def get_model(api_key):
        if not api_key: return None
        try:
            genai.configure(api_key=api_key)
            return genai.GenerativeModel('gemini-1.5-flash')
        except: return None

    @staticmethod
    def extract_text(file):
        try:
            ext = file.name.split('.')[-1].lower()
            if ext == 'pdf': return " ".join([p.extract_text() for p in PyPDF2.PdfReader(file).pages if p.extract_text()])
            elif ext == 'docx': return "\n".join([p.text for p in Document(file).paragraphs])
            return file.read().decode('utf-8', errors='ignore')
        except: return ""

    @staticmethod
    def summarize(text, model):
        if not model: return "تخصصات أخرى", text[:300]
        st.session_state['api_usage'] += 1
        prompt = f"لخص النص التالي باحترافية واختر قسماً واحداً من {CATEGORIES}. التنسيق: القسم: [الاسم] الملخص: [النص]. النص: {text[:10000]}"
        try:
            res = model.generate_content(prompt).text
            cat = "تخصصات أخرى"
            for c in CATEGORIES:
                if c in res: cat = c; break
            summ = res.split("الملخص:")[-1].strip() if "الملخص:" in res else res
            return cat, summ
        except: return "تخصصات أخرى", "فشل التلخيص"

# --- 5. واجهة المستخدم (كل المميزات السابقة) ---
st.sidebar.title("🚀 المكتبة الذكية Pro")
api_key = st.sidebar.text_input("Gemini API Key:", type="password")
model = AIProcessor.get_model(api_key)

if model:
    st.sidebar.success("AI نشط")
    st.sidebar.markdown(f'<div class="quota-card">الطلبات: {st.session_state["api_usage"]}</div>', unsafe_allow_html=True)

df = load_full_data()

# إحصائيات جانبية
st.sidebar.markdown("---")
if not df.empty:
    stats = df['category'].value_counts()
    for cat_name, count in stats.items():
        if st.sidebar.button(f"{cat_name} ({count})"):
            st.session_state['cat_selector'] = cat_name
            st.session_state['menu_selection'] = "🏠 المكتبة"

menu_options = ["🏠 المكتبة", "📖 الفهرس الشامل", "➕ إضافة مستند", "🔍 البحث والتحليل", "📊 التقارير والإعدادات"]
st.session_state['menu_selection'] = st.sidebar.selectbox("القائمة", menu_options, index=menu_options.index(st.session_state['menu_selection']))

# --- تنفيذ الصفحات ---

if st.session_state['menu_selection'] == "🏠 المكتبة":
    st.title("📚 مستودع المعرفة السحابي")
    
    cat_list = ["الكل"] + CATEGORIES
    st.session_state['cat_selector'] = st.selectbox("تصفية حسب القسم", cat_list, index=cat_list.index(st.session_state['cat_selector']))
    
    display_df = df if st.session_state['cat_selector'] == "الكل" else df[df['category'] == st.session_state['cat_selector']]
    
    if display_df.empty:
        st.info("لا توجد مستندات في هذا القسم.")
    else:
        for i, row in display_df.iterrows():
            with st.container():
                st.markdown(f'<div class="main-card"><h3>📘 {row["title"]}</h3><p><span class="status-badge">{row["category"]}</span> <span class="status-badge">{row["date"]}</span></p></div>', unsafe_allow_html=True)
                with st.expander("فتح التفاصيل"):
                    t1, t2 = st.tabs(["📝 الملخص", "📄 النص المستخرج"])
                    st.write(row['summary_text'])
                    with t2: st.text(row['raw_text'][:2000] if row['raw_text'] else "لا يوجد نص")
                    
                    if st.button("🗑️ حذف نهائي", key=f"del_{i}"):
                        df = df.drop(i)
                        save_full_data(df)
                        st.rerun()
                st.divider()

elif st.session_state['menu_selection'] == "📖 الفهرس الشامل":
    st.title("📖 الفهرس")
    if not df.empty:
        for i, row in df.iterrows():
            st.markdown(f"**{i+1}. {row['title']}** | القسم: {row['category']} | مضاف بتاريخ: {row['date']}")

elif st.session_state['menu_selection'] == "➕ إضافة مستند":
    st.title("➕ إضافة محتوى جديد")
    with st.form("add_form"):
        t = st.text_input("عنوان الكتاب/المقال")
        f = st.file_uploader("ارفع الملف")
        btn = st.form_submit_button("🚀 معالجة وحفظ")
        
        if btn and t and f:
            with st.spinner("جاري التحليل..."):
                raw = AIProcessor.extract_text(f)
                cat, summ = AIProcessor.summarize(raw, model)
                new_data = {
                    "id": len(df) + 1,
                    "title": t,
                    "category": cat,
                    "summary_text": summ,
                    "raw_text": raw[:5000],
                    "date": datetime.now().strftime("%Y-%m-%d")
                }
                df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                save_full_data(df)
                st.success("تم الحفظ بنجاح!")

elif st.session_state['menu_selection'] == "🔍 البحث والتحليل":
    st.title("🔍 البحث الذكي")
    q = st.text_input("ابحث عن أي كلمة في العنوان أو المحتوى...")
    if q and not df.empty:
        results = df[df['title'].str.contains(q, case=False) | df['raw_text'].str.contains(q, case=False)]
        st.write(f"تم العثور على ({len(results)}) نتيجة:")
        for i, r in results.iterrows():
            st.markdown(f'<div class="main-card"><h4>📌 {r["title"]}</h4><p>{r["summary_text"][:200]}...</p></div>', unsafe_allow_html=True)

elif st.session_state['menu_selection'] == "📊 التقارير والإعدادات":
    st.title("📊 لوحة التحكم")
    if not df.empty:
        st.bar_chart(df['category'].value_counts())
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 تحميل كافة البيانات (Excel/CSV)", csv, "library_backup.csv", "text/csv")
