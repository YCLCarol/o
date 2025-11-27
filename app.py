# app.py
import streamlit as st
import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
import re
import pandas as pd
from io import BytesIO
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import json
from pathlib import Path


# ---------------- 設定 ----------------
RULES_DIR = Path("customer_rules")
RULES_DIR.mkdir(exist_ok=True)

ADMIN_PASSWORD = "Arsenalnumber1"

# Session 狀態：是否為管理員
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False


# ---------------- 管理員登入區 ----------------
st.set_page_config(page_title="自動接單系統 Demo", layout="wide")

if not st.session_state["is_admin"]:
    st.sidebar.title("🔒 管理員登入（選填）")
    pwd = st.sidebar.text_input("管理員密碼", type="password")
    if st.sidebar.button("登入"):
        if pwd == ADMIN_PASSWORD:
            st.session_state["is_admin"] = True
            st.sidebar.success("登入成功！")
            st.rerun()
        else:
            st.sidebar.error("密碼錯誤")


# ---------------- Sample Rules（初始寫入） ----------------
SAMPLE_RULES = {
    "default": {
        "訂單編號": r"\b[0-9]{8,12}\b",
        "訂單日期": r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b",
        "編碼": r"\b[A-Z]{1}\d{3}-[A-Z]{1}\d{3}[A-Z]?\b",
        "品名": r"",
        "規格": r"\b[A-Z]{2}-\d{4}-\d{2}\b",
        "物料型號": r"\b[A-Z]{2}-\d{4}-\d{2}\b",
        "數量": r"\b\d+(?:,\d{3})*(?:\.\d+)?\b",
        "單位": r"\b[A-Z]{1,3}\b",
        "單價": r"\b\d+(?:,\d{3})*(?:\.\d+)?\b",
        "總價": r"\b\d+(?:,\d{3})*(?:\.\d+)?\b",
        "交期": r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"
    }
}

# 寫入 sample rules（僅第一次）
for name, rules in SAMPLE_RULES.items():
    fp = RULES_DIR / f"{name}.json"
    if not fp.exists():
        fp.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- 工具函式 ----------------
def list_customers():
    return sorted([p.stem for p in RULES_DIR.glob("*.json")])

def load_rules(customer_name):
    fp = RULES_DIR / f"{customer_name}.json"
    if not fp.exists():
        return {}
    return json.loads(fp.read_text(encoding="utf-8"))

def save_rules(customer_name, rules_dict):
    fp = RULES_DIR / f"{customer_name}.json"
    fp.write_text(json.dumps(rules_dict, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_text_from_pdf_bytes(pdf_bytes: bytes):
    text_content = ""

    # pdfplumber 先讀
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text_content += page.extract_text() or ""
        if text_content.strip():
            return text_content
    except:
        pass

    # OCR
    try:
        images = convert_from_bytes(pdf_bytes, dpi=300)
        for img in images:
            text_content += pytesseract.image_to_string(img, lang="eng+chi_tra") + "\n"
    except Exception as e:
        st.warning(f"OCR 影像處理失敗: {e}")

    return text_content


def extract_fields(text, rules: dict):
    data = {}
    for field, pattern in rules.items():
        if not pattern:
            data[field] = []
            continue
        try:
            matches = re.findall(pattern, text)
        except re.error:
            matches = []
        data[field] = matches
    return data


def to_excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="訂單明細")
    return output.getvalue()



# ---------------- 介面主體 ----------------
st.title("📄 自動接單系統")


# ---------------- 客戶選擇（所有人可用） ----------------
customers = list_customers()
if not customers:
    st.error("⚠ 尚無任何客戶規則，可由管理員新增")
    st.stop()

sel_customer = st.selectbox("📌 選擇客戶", customers)


# ---------------- 管理員功能區（只有管理員看得到） ----------------
if st.session_state["is_admin"]:
    st.sidebar.header("🔧 客戶規則管理（管理員）")

    # 新增客戶
    new_name = st.sidebar.text_input("新增新客戶名稱")
    if st.sidebar.button("建立新客戶"):
        if not new_name.strip():
            st.sidebar.warning("請輸入客戶名稱")
        else:
            target = RULES_DIR / f"{new_name}.json"
            if target.exists():
                st.sidebar.error("客戶已存在")
            else:
                base = load_rules(sel_customer)
                save_rules(new_name, base)
                st.sidebar.success("已建立")
                st.rerun()

    # 刪除客戶
    if st.sidebar.button("刪除此客戶規則"):
        confirm = st.sidebar.checkbox(f"⚠ 確認刪除 {sel_customer}？")
        if confirm:
            try:
                (RULES_DIR / f"{sel_customer}.json").unlink()
                st.sidebar.success("已刪除")
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"刪除失敗：{e}")

    # 顯示 & 編輯規則
    st.subheader(f"【管理員】客戶：{sel_customer} 的擷取規則 JSON")
    rules = load_rules(sel_customer)
    rules_text = json.dumps(rules, ensure_ascii=False, indent=2)
    edited = st.text_area("可編輯 JSON", value=rules_text, height=260)

    c1, c2 = st.columns(2)

    with c1:
        if st.button("💾 儲存規則"):
            try:
                parsed = json.loads(edited)
                save_rules(sel_customer, parsed)
                st.success("已儲存規則")
            except Exception as e:
                st.error(f"JSON 解析失敗：{e}")

    with c2:
        if st.button("🔍 檢查 Regex"):
            parsed = json.loads(edited)
            bad = []
            for k, p in parsed.items():
                if not p:
                    continue
                try:
                    re.compile(p)
                except re.error as e:
                    bad.append((k, str(e)))
            if bad:
                st.error("以下 regex 錯誤：")
                for k, msg in bad:
                    st.write(f"- {k}: {msg}")
            else:
                st.success("所有 regex 均正常")

    st.markdown("---")


# ---------------- PDF 上傳（所有使用者可用） ----------------
st.subheader("📤 上傳訂單 PDF 進行擷取")
uploaded_file = st.file_uploader("請上傳 PDF 檔", type=["pdf"])

if uploaded_file:
    pdf_bytes = uploaded_file.read()
    with st.spinner("OCR / 文字擷取中…"):
        text_content = extract_text_from_pdf_bytes(pdf_bytes)

    if not text_content.strip():
        st.warning("⚠ 無法擷取到內容，請換高畫質 PDF")
        st.stop()

    st.subheader("📄 擷取文字（預覽）")
    st.code(text_content[:1000] + ("\n...\n" if len(text_content) > 1000 else ""))

    # 擷取欄位
    rules = load_rules(sel_customer)
    extracted = extract_fields(text_content, rules)

    max_len = max((len(v) for v in extracted.values()), default=0)
    df = pd.DataFrame({k: v + [""] * (max_len - len(v)) for k, v in extracted.items()})

    st.subheader("📝 擷取結果（可編輯）")

    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(editable=True, resizable=True)
    grid_options = gb.build()
    grid_response = AgGrid(df, gridOptions=grid_options,
                           update_mode=GridUpdateMode.VALUE_CHANGED,
                           fit_columns_on_grid_load=True)
    df_updated = pd.DataFrame(grid_response["data"])

    col_dl, col_oracle = st.columns(2)

    with col_dl:
        excel_bytes = to_excel_bytes(df_updated)
        st.download_button(
            "📥 下載 Excel",
            excel_bytes,
            file_name=f"{sel_customer}_訂單明細.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with col_oracle:
        if st.button("🚀 模擬送出 Oracle"):
            st.write("送出資料：")
            st.dataframe(df_updated)
            st.success("已模擬送出 Oracle！")
