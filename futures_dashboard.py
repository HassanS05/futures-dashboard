import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# ---------------- PARAMÈTRES CONTRATS ----------------
contracts = {
    "MGC (Micro Gold Futures)": {"tick_size": 0.10, "tick_value": 1.0},
    "GC (Gold Futures)": {"tick_size": 0.10, "tick_value": 10.0},
    "MNQ (Micro Nasdaq Futures)": {"tick_size": 0.25, "tick_value": 0.50},
    "MES (Micro S&P Futures)": {"tick_size": 0.25, "tick_value": 1.25},
}

st.title("📈 Futures PnL Dashboard")

# ------------- CHOIX DU CONTRAT ----------------
contract = st.selectbox("Choisis ton contrat", list(contracts.keys()))
tick_size = contracts[contract]["tick_size"]
tick_value = contracts[contract]["tick_value"]

# ------------- ENTRÉES UTILISATEUR --------------
entry_price = st.number_input("Prix d'entrée", value=3358.0)
tp_price = st.number_input("Take Profit (TP)", value=3381.0)
sl_price = st.number_input("Stop Loss (SL)", value=3350.0)
qty = st.number_input("Nombre de contrats", min_value=1, step=1)

# ------------- RÉSUMÉ SCÉNARIO ------------------
st.subheader(f"📍 Scénario : {contract} | Entrée {entry_price} | TP {tp_price} | SL {sl_price} | {qty} contrat(s)")

# ------------- CALCULS PnL ----------------------
move_ticks_tp = round(abs(tp_price - entry_price) / tick_size)
move_ticks_sl = round(abs(entry_price - sl_price) / tick_size)

profit = move_ticks_tp * tick_value * qty
loss = move_ticks_sl * tick_value * qty
risk_reward = round(profit / loss, 2) if loss != 0 else "∞"

# ------------- AFFICHAGE MÉTRIQUES ----------------
st.metric("Ticks jusqu'au TP", move_ticks_tp)
st.metric("Ticks jusqu'au SL", move_ticks_sl)
st.metric("Gain potentiel (USD)", f"${profit:.2f}")
st.metric("Perte potentielle (USD)", f"${loss:.2f}")
st.metric("Ratio Risque / Récompense", risk_reward)

# ------------- GRAPHIQUE TRADE ---------------------
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=[0, 1], y=[sl_price, entry_price],
    fill='tozeroy', mode='none', name='Zone de Risque',
    fillcolor='rgba(255, 0, 0, 0.3)'
))
fig.add_trace(go.Scatter(
    x=[1, 2], y=[entry_price, tp_price],
    fill='tozeroy', mode='none', name='Zone de Gain',
    fillcolor='rgba(0, 255, 0, 0.3)'
))
fig.add_hline(y=sl_price, line=dict(color="red", dash="dot"), name="Stop Loss")
fig.add_hline(y=entry_price, line=dict(color="blue", dash="dash"), name="Entrée")
fig.add_hline(y=tp_price, line=dict(color="green", dash="dot"), name="Take Profit")

fig.update_layout(
    title="Visualisation du Trade",
    xaxis_title="Prix",
    yaxis=dict(showticklabels=False),
    showlegend=True,
    height=400
)

st.plotly_chart(fig)

# ------------- OBJECTIFS JOURNALIERS -----------------
st.header("📊 Suivi des Objectifs Hebdomadaires")

jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]
objectifs = [250, 300, 275, 200, 300]
resultats = []

for jour in jours:
    res = st.number_input(f"Résultat {jour}", min_value=0, max_value=1000, step=10)
    resultats.append(res)

total_semaine = sum(resultats)

df = pd.DataFrame({
    "Jour": jours,
    "Objectif": objectifs,
    "Résultat": resultats
})

# ------------- GRAPHIQUE BARRES ---------------------
fig2 = go.Figure()
fig2.add_trace(go.Bar(x=df["Jour"], y=df["Objectif"], name="Objectif", marker_color="orange"))
fig2.add_trace(go.Bar(x=df["Jour"], y=df["Résultat"], name="Résultat", marker_color="blue"))
fig2.add_trace(go.Scatter(
    x=["Vendredi"], y=[total_semaine],
    mode="markers+text",
    text=[f"{total_semaine}$"],
    textposition="top center",
    marker=dict(size=12, color="green", symbol="star"),
    name="Total Semaine"
))

fig2.update_layout(
    title="🎯 Objectifs vs Résultats Hebdomadaires",
    barmode="group",
    yaxis_title="Montant ($)",
    xaxis_title="Jour"
)

st.plotly_chart(fig2)
