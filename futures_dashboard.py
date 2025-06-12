import streamlit as st
from PIL import Image

# Affichage du logo en haut
st.image("assets/logo.png", width=80)



st.image(logo_url, width=80)

st.title("📊 Futures PnL Dashboard")
contracts = {
    "MGC (Micro Gold Futures)": {"tick_size": 0.10, "tick_value": 1.0},
    "GC (Gold Futures)": {"tick_size": 0.10, "tick_value": 10.0},
    "MNQ (Micro Nasdaq Futures)": {"tick_size": 0.25, "tick_value": 0.50},
    "MES (Micro S&P Futures)": {"tick_size": 0.25, "tick_value": 1.25},
}



contract = st.selectbox("Choisis ton contrat", list(contracts.keys()))
tick_size = contracts[contract]["tick_size"]
tick_value = contracts[contract]["tick_value"]

entry_price = st.number_input("Prix d'entrée", value=3358.0)
tp_price = st.number_input("Take Profit (TP)", value=3381.0)
sl_price = st.number_input("Stop Loss (SL)", value=3350.0)
qty = st.number_input("Nombre de contrats", min_value=1, step=1)
st.subheader(f"🧠 Scénario : {contract} | Entrée {entry_price} | TP {tp_price} | SL {sl_price} | {qty} contrat(s)")

move_ticks_tp = round(abs(tp_price - entry_price) / tick_size)
move_ticks_sl = round(abs(entry_price - sl_price) / tick_size)

profit = move_ticks_tp * tick_value * qty
loss = move_ticks_sl * tick_value * qty
risk_reward = round(profit / loss, 2) if loss != 0 else "∞"

st.metric("Ticks jusqu'au TP", move_ticks_tp)
st.metric("Ticks jusqu'au SL", move_ticks_sl)
st.metric("Gain potentiel (USD)", f"${profit:.2f}")
st.metric("Perte potentielle (USD)", f"${loss:.2f}")
st.metric("Ratio Risque / Récompense", risk_reward)
import plotly.graph_objects as go

fig = go.Figure()

fig.add_trace(go.Scatter(
    x=[0, 1], y=[sl_price, entry_price],
    fill='tozeroy',
    mode='none',
    name='Zone de Risque',
    fillcolor='rgba(255, 0, 0, 0.3)'
))

fig.add_trace(go.Scatter(
    x=[1, 2], y=[entry_price, tp_price],
    fill='tozeroy',
    mode='none',
    name='Zone de Gain',
    fillcolor='rgba(0, 255, 0, 0.3)'
))

fig.add_hline(y=sl_price, line=dict(color="red", dash="dot"), name="Stop Loss")
fig.add_hline(y=entry_price, line=dict(color="blue", dash="dash"), name="Entrée")
fig.add_hline(y=tp_price, line=dict(color="green", dash="dot"), name="Take Profit")

fig.update_layout(
    title="Visualisation du Trade",
    yaxis_title="Prix",
    xaxis=dict(showticklabels=False),
    showlegend=True,
    height=400
)

st.plotly_chart(fig)
