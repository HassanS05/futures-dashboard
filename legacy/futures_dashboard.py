import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# ---------------------- PNL DASHBOARD ----------------------
st.title("📊 Futures PnL Dashboard")

# Contrats & caractéristiques
contracts = {
    "MGC (Micro Gold Futures)": {"tick_size": 0.10, "tick_value": 1.0},
    "GC (Gold Futures)": {"tick_size": 0.10, "tick_value": 10.0},
    "MNQ (Micro Nasdaq Futures)": {"tick_size": 0.25, "tick_value": 0.50},
    "MES (Micro S&P Futures)": {"tick_size": 0.25, "tick_value": 1.25},
}

# Choix du contrat
contract = st.selectbox("Choisis ton contrat", list(contracts.keys()))
tick_size = contracts[contract]["tick_size"]
tick_value = contracts[contract]["tick_value"]

# Entrées utilisateur
entry_price = st.number_input("Prix d'entrée", value=3358.0)
tp_price = st.number_input("Take Profit (TP)", value=3381.0)
sl_price = st.number_input("Stop Loss (SL)", value=3350.0)
qty = st.number_input("Nombre de contrats", min_value=1, step=1)

# Résumé
st.subheader(f"📍 Scénario : {contract} | Entrée {entry_price} | TP {tp_price} | SL {sl_price} | {qty} contrat(s)")

# Calculs
move_ticks_tp = round(abs(tp_price - entry_price) / tick_size)
move_ticks_sl = round(abs(entry_price - sl_price) / tick_size)

profit = move_ticks_tp * tick_value * qty
loss = move_ticks_sl * tick_value * qty
risk_reward = round(profit / loss, 2) if loss != 0 else "∞"

# Métriques
st.metric("Ticks jusqu'au TP", move_ticks_tp)
st.metric("Ticks jusqu'au SL", move_ticks_sl)
st.metric("Gain potentiel (USD)", f"${profit:.2f}")
st.metric("Perte potentielle (USD)", f"${loss:.2f}")
st.metric("Ratio Risque / Récompense", risk_reward)

# Graphique de zone de risque/gain
fig = go.Figure()

fig.add_trace(go.Scatter(
    x=[entry_price, tp_price],
    y=[0, 1],
    mode="lines+markers",
    name="Zone de Gain",
    line=dict(color="green", width=4)
))

fig.add_trace(go.Scatter(
    x=[entry_price, sl_price],
    y=[0, -1],
    mode="lines+markers",
    name="Zone de Risque",
    line=dict(color="red", width=4)
))

fig.update_layout(
    title="Visualisation du Trade",
    xaxis_title="Prix",
    yaxis_title="PnL",
    showlegend=True,
    height=400
)

st.plotly_chart(fig)

# ------------------ OBJECTIFS SUR 10 JOURS -------------------
st.header("📊 Suivi des Objectifs sur 10 Jours")

jours = [
    "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi",
    "Lundi 2", "Mardi 2", "Mercredi 2", "Jeudi 2", "Vendredi 2"
]
objectif_journalier = 800
objectifs = [objectif_journalier] * len(jours)

# Entrée des résultats
resultats = []
for jour in jours:
    res = st.number_input(f"Résultat pour {jour}", min_value=0, max_value=3000, step=10)
    resultats.append(res)

# Total semaine
total_resultat = sum(resultats)

# Ajouter Total 10 jours comme 11e colonne
jours_affiche = jours + ["Total 10 jours"]
objectifs_affiche = objectifs + [8000]
resultats_affiche = resultats + [total_resultat]

# Créer DataFrame
df = pd.DataFrame({
    "Jour": jours_affiche,
    "Objectif": objectifs_affiche,
    "Résultat": resultats_affiche
})

# Affichage graphique
fig2 = go.Figure()

fig2.add_trace(go.Bar(
    x=df["Jour"],
    y=df["Objectif"],
    name="Objectif (800$/jour)",
    marker_color="blue"
))

fig2.add_trace(go.Bar(
    x=df["Jour"],
    y=df["Résultat"],
    name="Résultat",
    marker_color="green"
))

fig2.update_layout(
    title="🎯 Objectif vs Résultat | 10 jours",
    barmode="group",
    yaxis_title="Montant ($)",
    xaxis_title="Jour",
    height=500
)

st.plotly_chart(fig2)
