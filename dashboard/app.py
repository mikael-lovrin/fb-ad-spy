# -*- coding: utf-8 -*-
"""
Dashboard Streamlit para navegação e análise dos anúncios coletados.
Rodar com: streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd

from storage.database import init_db, query_ads, get_stats
from core.keywords import get_available_nichos

st.set_page_config(
    page_title="FB Ad Spy — MRD",
    page_icon="🕵️",
    layout="wide",
)

init_db()

# ── Sidebar: Filtros ───────────────────────────────────────────────────────────
st.sidebar.title("🕵️ FB Ad Spy")
st.sidebar.markdown("---")

nichos = ["Todos"] + get_available_nichos()
selected_nicho = st.sidebar.selectbox("Nicho", nichos)
min_days = st.sidebar.slider("Dias rodando mínimo", 0, 180, 7)
min_score = st.sidebar.slider("Swipe Score mínimo", 0, 100, 0)
active_only = st.sidebar.checkbox("Apenas ativos", value=True)
limit = st.sidebar.number_input("Limite de resultados", 10, 1000, 200)

st.sidebar.markdown("---")
st.sidebar.markdown("**📊 Banco de dados**")
stats = get_stats()
st.sidebar.metric("Total de anúncios", stats["total"])
st.sidebar.metric("Ativos", stats["active"])
st.sidebar.metric("Analisados", stats["analyzed"])

# ── Coleta rápida no dashboard ─────────────────────────────────────────────────
st.sidebar.markdown("---")
with st.sidebar.expander("⚡ Coletar agora"):
    quick_nicho = st.selectbox("Nicho", get_available_nichos(), key="q_nicho")
    quick_count = st.number_input("Quantidade", 10, 500, 50, key="q_count")
    quick_country = st.selectbox("País", ["BR", "US", "ALL"], key="q_country")
    if st.button("🚀 Coletar"):
        with st.spinner("Coletando..."):
            from main import collect_ads
            from storage.database import bulk_upsert
            ads = collect_ads(quick_nicho, quick_count, quick_country)
            result = bulk_upsert(ads)
            st.success(f"✅ {result['inserted']} anúncios salvos!")

# ── Main area ──────────────────────────────────────────────────────────────────
st.title("🕵️ Facebook Ad Spy — Marketing de Resposta Direta")

# Query
nicho_filter = None if selected_nicho == "Todos" else selected_nicho
ads = query_ads(
    nicho=nicho_filter,
    min_days=min_days,
    min_score=min_score,
    active_only=active_only,
    limit=int(limit),
)

if not ads:
    st.warning("Nenhum anúncio encontrado com esses filtros. Tente coletar primeiro.")
    st.stop()

df = pd.DataFrame(ads)

# ── Métricas rápidas ───────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Anúncios exibidos", len(df))
col2.metric("Score médio", f"{df['swipe_score'].mean():.0f}" if "swipe_score" in df else "—")
col3.metric("Dias rodando (média)", f"{df['days_running'].mean():.0f}" if "days_running" in df else "—")
col4.metric("Nichos únicos", df["industry"].nunique() if "industry" in df else 0)

st.markdown("---")

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Tabela", "🔍 Detalhes", "📈 Insights"])

with tab1:
    display_cols = [
        "page_name", "industry", "days_running", "swipe_score",
        "ad_type", "hook", "text_summary", "ad_snapshot_url"
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[display_cols].rename(columns={
            "page_name": "Página",
            "industry": "Nicho",
            "days_running": "Dias",
            "swipe_score": "Score",
            "ad_type": "Tipo",
            "hook": "Hook",
            "text_summary": "Resumo",
            "ad_snapshot_url": "Link",
        }),
        use_container_width=True,
        height=500,
    )

    # Export
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Exportar CSV", csv, "ads_export.csv", "text/csv")

with tab2:
    if len(df) == 0:
        st.info("Nenhum anúncio para exibir.")
    else:
        selected_idx = st.selectbox(
            "Selecione um anúncio",
            range(len(df)),
            format_func=lambda i: f"[Score {df.iloc[i].get('swipe_score', 0)}] {df.iloc[i].get('page_name', '')} — {df.iloc[i].get('industry', '')} ({df.iloc[i].get('days_running', 0)} dias)"
        )

        ad = df.iloc[selected_idx]

        col_a, col_b = st.columns([1, 1])

        with col_a:
            st.subheader(f"🏢 {ad.get('page_name', 'Sem nome')}")
            st.markdown(f"**Nicho:** {ad.get('industry', '—')}")
            st.markdown(f"**Tipo:** {ad.get('ad_type', '—').upper() if ad.get('ad_type') else '—'}")
            st.markdown(f"**Dias rodando:** {ad.get('days_running', '—')}")
            st.markdown(f"**Swipe Score:** {'⭐' * min(int((ad.get('swipe_score') or 0) // 20), 5)} ({ad.get('swipe_score', 0)}/100)")

            if ad.get("ad_snapshot_url"):
                st.markdown(f"[🔗 Ver anúncio na biblioteca]({ad['ad_snapshot_url']})")

            st.markdown("---")
            st.markdown("**Hook:**")
            st.info(ad.get("hook") or "—")

            st.markdown("**Copy:**")
            st.text_area("", ad.get("ad_body") or "—", height=150, disabled=True)

        with col_b:
            st.markdown("**Resumo da análise:**")
            st.write(ad.get("text_summary") or "—")

            if ad.get("pain_points"):
                st.markdown("**Dores endereçadas:**")
                st.write(ad["pain_points"])

            if ad.get("benefits"):
                st.markdown("**Promessas/benefícios:**")
                st.write(ad["benefits"])

            if ad.get("video_analysis"):
                st.markdown("**Análise do vídeo:**")
                st.write(ad["video_analysis"])

            if ad.get("image_analysis"):
                st.markdown("**Análise da imagem:**")
                st.write(ad["image_analysis"])

with tab3:
    if "industry" in df.columns and df["industry"].notna().any():
        st.subheader("Anúncios por nicho")
        nicho_counts = df["industry"].value_counts()
        st.bar_chart(nicho_counts)

    if "days_running" in df.columns:
        st.subheader("Distribuição de dias rodando")
        st.bar_chart(df["days_running"].dropna().value_counts().sort_index())

    if "swipe_score" in df.columns:
        st.subheader("Top 10 por Swipe Score")
        top = df.nlargest(10, "swipe_score")[["page_name", "industry", "days_running", "swipe_score", "hook"]]
        st.dataframe(top, use_container_width=True)
