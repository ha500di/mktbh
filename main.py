import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- إعدادات الصفحة ---
st.set_page_config(page_title="المكتبة الذكية السحابية", page_icon="☁️", layout="wide")

# --- رابط جوجل شيت (ضع رابط جدولك هنا) ---
# ملاحظة: يفضل وضع الرابط في "Secrets" بـ Streamlit Cloud، لكن للسهولة سنضعه هنا مؤقتاً
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1ERRHdDEHDGqhIpa_x5T3pUDXEYXfGC8y7ysMCrYQ15k/edit?usp=sharing"

# --- الاتصال بجوجل شيت ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data():
    try:
        return conn.read(spreadsheet=SPREADSHEET_URL, ttl=0)
    except:
        # إذا كان الجدول فارغاً تماماً، ننشئ الأعمدة الأساسية
        return pd.DataFrame(columns=["ID", "Title", "Category", "Summary", "RawText", "Date"])

def save_data(df):
    conn.update(spreadsheet=SPREADSHEET_URL, data=df)
    st.cache_data.clear()

# --- واجهة البرنامج المبسطة ---
st.title("📚 مكتبتي الذكية (نسخة جوجل شيت)")

# إعداد AI
api_key = st.sidebar.text_input("Gemini API Key:", type="password")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

menu = st.sidebar.selectbox("القائمة", ["🏠 عرض المكتبة", "➕ إضافة كتاب جديد"])

df = get_data()

if menu == "🏠 عرض المكتبة":
    if df.empty or len(df) == 0:
        st.info("المكتبة فارغة حالياً. اضف أول كتاب!")
    else:
        for i, row in df.iterrows():
            with st.expander(f"📘 {row['Title']} - ({row['Category']})"):
                st.write(f"**التلخيص:** {row['Summary']}")
                st.caption(f"تاريخ الإضافة: {row['Date']}")
                if st.button("حذف", key=f"del_{i}"):
                    df = df.drop(i)
                    save_data(df)
                    st.rerun()

elif menu == "➕ إضافة كتاب جديد":
    with st.form("add_form"):
        title = st.text_input("عنوان الكتاب")
        cat = st.selectbox("القسم", ["عام", "تقنية", "ديني", "رواية", "أخرى"])
        file = st.file_uploader("ارفع ملف (PDF أو Word)")
        submit = st.form_submit_button("حفظ ومعالجة بالذكاء الاصطناعي")
        
        if submit and title and file and model:
            with st.spinner("جاري القراءة والتلخيص..."):
                # استخراج النص (تبسيط)
                try:
                    reader = PyPDF2.PdfReader(file)
                    text = " ".join([p.extract_text() for p in reader.pages[:5]]) # أول 5 صفحات للسرعة
                except:
                    text = "فشل استخراج النص"
                
                # التلخيص بالذكاء الاصطناعي
                prompt = f"لخص هذا النص في نقاط قصيرة ومفيدة بالعربية: {text[:3000]}"
                summary = model.generate_content(prompt).text
                
                # إضافة للجدول
                new_row = {
                    "ID": len(df) + 1,
                    "Title": title,
                    "Category": cat,
                    "Summary": summary,
                    "RawText": text[:500],
                    "Date": datetime.now().strftime("%Y-%m-%d")
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df)
                st.success("تم الحفظ في جوجل شيت!")
