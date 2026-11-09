from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from uuid import uuid4

import streamlit as st

from database import (
    STATUSES,
    add_case_note,
    create_case,
    get_case_notes,
    get_cases,
    init_db,
    transition_case,
    save_case_design,
    verify_user_login,
    get_designers_list,
    assign_case_to_designer,
)

APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ROLE_NAMES = {
    "dashboard": "لوحة التحكم العامة",
    "representative": "المندوب",
    "cad": "مصمم CAD",
    "cam": "الخراطة CAM",
    "ceramic": "السيرامست",
}

STAGE_CONFIG = {
    "cad": {
        "role": ROLE_NAMES["cad"],
        "statuses": ("cad_pending", "cad_in_progress"),
        "title": "محطة تصميم CAD",
        "description": "راجع الحالات الموجهة إليك بالاسم من المدير، ابدأ التصميم، وارفع ملف الـ 3D للإحالة.",
    },
    "cam": {
        "role": ROLE_NAMES["cam"],
        "statuses": ("cam_pending", "cam_in_progress"),
        "title": "محطة الخراطة CAM",
        "description": "قم بتنزيل ملف التصميم المنجز من CAD وتابع أعمال الخراطة (تم حجب السكنر الأصلي).",
    },
    "ceramic": {
        "role": ROLE_NAMES["ceramic"],
        "statuses": ("ceramic_pending", "ceramic_in_progress"),
        "title": "محطة السيراميك",
        "description": "أكمل أعمال السيراميك بناءً على الملاحظات الفنية المسجلة (تم حجب جميع الملفات).",
    },
}

st.set_page_config(
    page_title="إدارة مختبر الأسنان",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    html, body, [class*="css"], [data-testid="stAppViewContainer"] {
        direction: rtl;
        text-align: right;
    }
    [data-testid="stSidebar"] { direction: rtl; }
    [data-testid="stHorizontalBlock"] { direction: rtl; }
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"] {
        text-align: right;
    }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }
    .page-kicker {
        color: #64748b;
        font-size: 0.9rem;
        margin-bottom: -0.7rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()


def show_case(case: dict, stage: str | None = None, actor: str | None = None, user_role: str | None = None, manager_name: str | None = None) -> None:
    """Render a case summary, restricting files based on the employee's role and handling assignment."""
    with st.container(border=True):
        title_col, status_col = st.columns(2)
        with title_col:
            st.subheader(f"{case['case_number']} · {case['patient_name']}")
        with status_col:
            st.markdown(f"**{STATUSES.get(case['status'], case['status'])}**")

        info_cols = st.columns(4)
        with info_cols[0]:
            st.caption("العيادة")
            st.write(case["clinic_name"])
        with info_cols[1]:
            st.caption("درجة اللون")
            st.write(case["tooth_shade"])
        with info_cols[2]:
            st.caption("الأولوية")
            st.write(case["priority"])
        with info_cols[3]:
            st.caption("موعد التسليم")
            st.write(case["due_date"])

        if case.get("assigned_designer_name"):
            st.caption("المصمم المعين للحالة")
            st.info(f"💻 تم التوجيه إلى: {case['assigned_designer_name']}")

        if case.get("representative_notes"):
            st.caption("ملاحظات المندوب")
            st.write(case["representative_notes"])

        if user_role == "dashboard" and case["status"] == "assign_pending":
            st.subheader("🎯 توجيه وتعيين الحالة لمصمم")
            designers = get_designers_list()
            if not designers:
                st.warning("⚠️ لا يوجد مصممو CAD مسجلون في النظام حالياً لإحالة الحالة إليهم. أضف مصمماً من لوحة شؤون الموظفين بالأسفل.")
            else:
                designer_options = {d["full_name"]: d["username"] for d in designers}
                selected_d_name = st.selectbox("اختر المصمم المسؤول عن الحالة:", list(designer_options), key=f"assign-select-{case['id']}")
                if st.button("تأكيد وتوجيه الحالة للمصمم", key=f"assign-btn-{case['id']}", type="primary"):
                    if assign_case_to_designer(case["id"], designer_options[selected_d_name], selected_d_name, manager_name):
                        st.success(f"تم توجيه الحالة بنجاح للمصمم {selected_d_name}!")
                        st.rerun()

        if user_role in ["representative", "cad", "dashboard"] and case["status"] != "assign_pending":
            scanner_path = Path(case["scanner_path"])
            if scanner_path.is_file():
                st.download_button(
                    "⬇️ تنزيل ملف السكنر الأصلي",
                    data=scanner_path.read_bytes(),
                    file_name=case["scanner_filename"],
                    key=f"download-scanner-{case['id']}",
                )
            else:
                st.warning("ملف السكنر غير موجود في مجلد الملفات.")

        if user_role in ["cam", "dashboard"] and case.get("design_path"):
            design_path = Path(case["design_path"])
            if design_path.is_file():
                st.success(f"📁 ملف التصميم المرفوع: {case['design_filename']}")
                st.download_button(
                    "💾 تنزيل ملف التصميم ثلاثي الأبعاد (CAD Design)",
                    data=design_path.read_bytes(),
                    file_name=case["design_filename"],
                    key=f"download-design-{case['id']}",
                )

        if user_role == "ceramic":
            st.info("ℹ️ محطة السيراميك: تم حجب ملفات السكنر والتصميم. يرجى مراجعة سجل الملاحظات وتفاصيل الحالة بالأسفل لبناء الخزف والتلوين.")

        notes = get_case_notes(case["id"])
        with st.expander(f"سجل الملاحظات والتتبع للفريق ({len(notes)})"):
            if notes:
                for note in notes:
                    st.markdown(f"**{note['role']}** · {note['created_at']}")
                    st.write(note["body"])
                    st.divider()
            else:
                st.caption("لا توجد ملاحظات إضافية.")

        if stage:
            stage_statuses = STAGE_CONFIG[stage]["statuses"]
            current = case["status"]
            action_col, note_col = st.columns(2)
            
            if current == stage_statuses[0]:
                with action_col:
                    if st.button(
                        "بدء المرحلة",
                        key=f"start-{stage}-{case['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        ok, message = transition_case(
                            case["id"], stage, "start", actor
                        )
                        (st.success if ok else st.error)(message)
                        if ok:
                            st.rerun()
            elif current == stage_statuses[1]:
                with action_col:
                    uploaded_design = None
                    if stage == "cad":
                        uploaded_design = st.file_uploader(
                            "ارفع ملف التصميم النهائي المكتمل (STL / OBJ) *",
                            type=["stl", "obj", "ply", "zip"],
                            key=f"cad-file-upload-{case['id']}"
                        )
                        
                    if st.button(
                        "إنهاء وإحالة للمرحلة التالية",
                        key=f"complete-{stage}-{case['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        if stage == "cad" and not uploaded_design:
                            st.error("⚠️ يرجى رفع ملف التصميم النهائي أولاً لإتمام الإحالة إلى قِسم الخراطة.")
                        else:
                            if stage == "cad" and uploaded_design:
                                suffix = Path(uploaded_design.name).suffix.lower()
                                stored_name = f"design_{uuid4().hex}{suffix}"
                                stored_path = UPLOAD_DIR / stored_name
                                stored_path.write_bytes(uploaded_design.getvalue())
                                save_case_design(case["id"], str(stored_path), uploaded_design.name)
                                add_case_note(case["id"], actor, f"📥 تم رفع ملف التصميم الجاهز: {uploaded_design.name}")
                            
                            ok, message = transition_case(
                                case["id"], stage, "complete", actor
                            )
                            (st.success if ok else st.error)(message)
                            if ok:
                                st.rerun()

            with note_col:
                with st.form(f"note-form-{stage}-{case['id']}"):
                    note_text = st.text_area(
                        "إضافة ملاحظة فنية للحالة باسمك",
                        key=f"note-text-{stage}-{case['id']}",
                        height=70,
                    )
                    submitted = st.form_submit_button("حفظ الملاحظة في السجل")
                    if submitted:
                        if add_case_note(case["id"], actor, note_text):
                            st.success("تم حفظ الملاحظة.")
                            st.rerun()
                        else:
                            st.warning("اكتب الملاحظة أولاً.")
def show_dashboard(manager_name: str) -> None:
    st.markdown('<p class="page-kicker">نظرة سريعة على سير العمل</p>', unsafe_allow_html=True)
    st.title("لوحة التحكم العامة")
    all_cases = get_cases()

    total = len(all_cases)
    completed = sum(case["status"] == "completed" for case in all_cases)
    in_progress = sum(case["status"].endswith("_in_progress") for case in all_cases)
    waiting = sum(case["status"] in ["assign_pending", "cad_pending", "cam_pending", "ceramic_pending"] for case in all_cases)

    # التصحيح النهائي: إزالة الـ with واستعمال المصفوفة المباشرة للأعمدة الأربعة لمنع انهيار السيرفر
    metric_cols = st.columns(4)
    metric_cols[0].metric("إجمالي الحالات", total)
    metric_cols[1].metric("بانتظار الإجراء/التوزيع", waiting)
    metric_cols[2].metric("قيد العمل", in_progress)
    metric_cols[3].metric("مكتملة", completed)

    st.divider()
    with st.expander("➕ شؤون الموظفين (إضافة مصمم أو فني جديد إلى النظام)"):
        import sqlite3
        from database import DATABASE_PATH
        st.subheader("تسجيل حساب موظف جديد")
        with st.form("add-new-user-form", clear_on_submit=True):
            new_user_name = st.text_input("اسم المستخدم للدخول (بالإنجليزي وبدون فراغات) *")
            new_password = st.text_input("الرمز السري للدخول *", type="password")
            new_full_name = st.text_input("الاسم الكامل للموظف (يظهر في سجل الملاحظات والإحالات) *")
            new_role = st.selectbox("قسم الموظف وصلاحياته *", [
                "dashboard", "representative", "cad", "cam", "ceramic"
            ], format_func=lambda x: ROLE_NAMES[x])
            
            submit_user = st.form_submit_button("حفظ الموظف وتفعيل حسابه فوراً", type="primary")
            
            if submit_user:
                if not new_user_name.strip() or not new_password or not new_full_name.strip():
                    st.error("يرجى ملء جميع الحقول المطلوبة للموظف.")
                else:
                    try:
                        conn = sqlite3.connect(DATABASE_PATH)
                        conn.execute(
                            "INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
                            (new_user_name.strip().lower(), new_password, new_role, new_full_name.strip())
                        )
                        conn.commit()
                        conn.close()
                        st.success(f"✅ تم تفعيل حساب الموظف ({new_full_name.strip()}) بنجاح في قسم {ROLE_NAMES[new_role]}!")
                    except sqlite3.IntegrityError:
                        st.error("⚠️ اسم المستخدم هذا مسجل مسبقاً لموظف آخر. اختر اسم مستخدم مختلف.")

    st.divider()
    search_col, status_col = st.columns(2)
    with search_col:
        search = st.text_input("بحث برقم الحالة أو اسم المريض أو العيادة")
    with status_col:
        status_labels = {"الكل": None}
        status_labels.update({label: key for key, label in STATUSES.items()})
        selected_status = st.selectbox("تصفية حسب الحالة", list(status_labels))
    
    selected_key = status_labels[selected_status]
    filtered = get_cases(
        statuses=[selected_key] if selected_key else None,
        search=search,
    )

    st.subheader("جدول الحالات والمراقبة")
    if not filtered:
        st.info("لا توجد حالات مطابقة حالياً.")
    else:
        for case in filtered:
            show_case(case, user_role="dashboard", manager_name=manager_name)


def show_representative() -> None:
    st.title("استقبال حالة جديدة")
    st.write("أدخل بيانات الحالة وارفع ملف السكنر لإحالتها مباشرة إلى لوحة المدير للتوزيع.")

    st.session_state.setdefault("uploader_generation", 0)
    uploaded_file = st.file_uploader(
        "ملف السكنر",
        type=["stl", "obj", "ply", "zip", "dcm", "dicom", "jpg", "jpeg", "png", "pdf"],
        help="الملفات تحفظ محلياً داخل مجلد uploads في المشروع.",
        key=f"scanner-upload-{st.session_state['uploader_generation']}",
    )

    with st.form("new-case-form", clear_on_submit=True):
        patient_name = st.text_input("اسم المريض *")
        clinic_name = st.text_input("اسم العيادة *")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            tooth_shade = st.text_input("درجة اللون (الشيد) *", placeholder="مثال: A2 أو 3M2")
        with col_b:
            priority = st.selectbox("الأولوية", ["عادي", "مستعجل", "عاجل"])
        with col_c:
            due_date = st.date_input("موعد التسليم", value=date.today())
            
        representative_notes = st.text_area(
            "ملاحظات وتعليمات للمختبر",
            placeholder="مثال: نوع التعويض، الأسنان المطلوبة، أو تعليمات خاصة",
        )
        submitted = st.form_submit_button(
            "حفظ الحالة وتحويلها للمدير للتوزيع",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not patient_name.strip() or not clinic_name.strip() or not tooth_shade.strip():
            st.error("يرجى إدخال اسم المريض، اسم العيادة، ودرجة اللون (الشيد).")
        elif uploaded_file is None:
            st.error("يرجى رفع ملف السكنر قبل حفظ الحالة.")
        else:
            suffix = Path(uploaded_file.name).suffix.lower()
            stored_name = f"{uuid4().hex}{suffix}"
            stored_path = UPLOAD_DIR / stored_name
            try:
                stored_path.write_bytes(uploaded_file.getvalue())
                case_id = create_case(
                    patient_name=patient_name,
                    clinic_name=clinic_name,
                    tooth_shade=tooth_shade,
                    priority=priority,
                    due_date=due_date,
                    scanner_path=str(stored_path),
                    scanner_filename=Path(uploaded_file.name).name,
                    representative_notes=representative_notes,
                )
            except Exception as exc:
                stored_path.unlink(missing_ok=True)
                st.error(f"تعذر حفظ الحالة: {exc}")
            else:
                st.session_state["uploader_generation"] += 1
                st.success(f"تم إنشاء الحالة {case_id} بنجاح وتحويلها لمدير المختبر لتعيين المصمم.")
                st.rerun()

    st.divider()
    st.subheader("الحالات التي استقبلتها مؤخراً")
    recent = get_cases(search="")
    if recent:
        for case in recent[:5]:
            show_case(case, user_role="representative")
    else:
        st.info("لم تُسجل حالات بعد.")


def show_stage(stage: str, actor_name: str, username: str) -> None:
    config = STAGE_CONFIG[stage]
    st.title(config["title"])
    st.write(config["description"])

    search = st.text_input("بحث برقم الحالة أو اسم المريض أو العيادة")
    cases = get_cases(statuses=config["statuses"], search=search)
    
    if stage == "cad":
        cases = [c for c in cases if c.get("assigned_designer_username") == username]

    st.caption(f"{len(cases)} حالة مخصصة لك في هذه المحطة")
    if not cases:
        st.info("لا توجد حالات بانتظار عملك حالياً في هذه المحطة.")
        return

    for case in cases:
        show_case(case, stage=stage, actor=actor_name, user_role=stage)


def require_user_login(role: str) -> dict[str, Any] | None:
    """Show login form demanding unique Username and Password from database."""
    session_key = f"current_user_{role}"
    if session_key in st.session_state:
        return st.session_state[session_key]

    st.title(f"الدخول إلى {ROLE_NAMES[role]}")
    st.write("الرجاء إدخال اسم المستخدم والرمز السري الخاص بك لتسجيل الدخول الفردي للمحطة.")
    
    with st.form(f"login-form-{role}", clear_on_submit=True):
        username = st.text_input("اسم المستخدم (Username)", key=f"user-in-{role}")
        password = st.text_input("الرمز السري (Password)", type="password", key=f"pass-in-{role}")
        submitted = st.form_submit_button("تسجيل الدخول والتأكيد", type="primary")

    if submitted:
        user_data = verify_user_login(username, password, role)
        if user_data:
            st.session_state[session_key] = user_data
            st.success(f"مرحباً بك {user_data['full_name']}!")
            st.rerun()
        else:
            st.error("❌ اسم المستخدم أو الرمز السري غير صحيح، أو الحساب لا ينتمي لهذا القسم.")

    return None


def main() -> None:
    with st.sidebar:
        st.title("🦷 مختبر الأسنان")
        st.caption("إدارة التوزيع المركزي والتتبع المتقدم")
        selected_role = st.radio(
            "اختر مساحة العمل",
            options=list(ROLE_NAMES),
            format_func=lambda role: ROLE_NAMES[role],
            label_visibility="collapsed",
        )
        st.divider()
        
        session_key = f"current_user_{selected_role}"
        if session_key in st.session_state:
            logged_user = st.session_state[session_key]
            st.success(f"👤 الموظف: {logged_user['full_name']}")
            if st.button("تسجيل الخروج من الحساب", key=f"logout-btn-{selected_role}"):
                del st.session_state[session_key]
                st.rerun()

    user_info = require_user_login(selected_role)
    if not user_info:
        return

    if selected_role == "dashboard":
        show_dashboard(manager_name=user_info["full_name"])
    elif selected_role == "representative":
        show_representative()
    else:
        show_stage(selected_role, actor_name=user_info["full_name"], username=user_info["username"])


if __name__ == "__main__":
    main()
