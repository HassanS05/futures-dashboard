# HR5 Invest — Design System & Landing (2026)

Direction artistique : **fintech premium, sobre, institutionnelle** (références :
Linear, Stripe, Mercury, Bloomberg moderne). Objectif landing : **conversion**
vers l'inscription, en prouvant *clarté + intelligence + sérieux*.

## 1. Sitemap
```
/welcome (= /landing)  Site public marketing (conversion)
   Hero → Preuve sociale → Multi-actifs → Copilote IA (6 agents)
   → Comment ça marche → Analytique → Tarifs → Témoignage → FAQ → CTA → Footer
/  (app)  Terminal "Institutional Desk" (login → dashboard, existant)
```

## 2. Couleurs (HEX)
| Token | HEX | Usage |
|---|---|---|
| ink | `#06070A` | fond global |
| surface | `#0D0F14` | sections/cartes |
| surface2 | `#12151B` | cartes internes |
| line | `#1B1F27` | bordures |
| txt | `#EAECF2` | texte principal |
| muted | `#8A92A3` | texte secondaire |
| faint | `#5B6273` | légendes |
| brand | `#5B7CFA` | accent primaire |
| brand-600 | `#4A66E8` | hover/dégradé |
| brand-sky | `#46B6E6` | dégradé secondaire |
| up | `#2FCB83` | hausse / succès |
| down | `#FF5C6C` | baisse / risque |
| gold | `#D9B679` | signature premium (parcimonie) |

Dégradés : `linear-gradient(135deg,#5B7CFA,#4A66E8)` (boutons),
`linear-gradient(135deg,#8AA0FF,#5FC4EA)` (texte titre).

## 3. Typographie
- **Inter** (400/500/600/700/800) : UI & marketing. **JetBrains Mono** : chiffres.
- Échelle : Display `60px/800`, H1 `clamp 36→60`, H2 `30–36/700`, H3 `18/600`,
  corps `16–18/400`, légende `12–13`, micro `10–11` (uppercase, tracking .08–.14em).
- `line-height` corps 1.6 ; titres 1.05–1.2 ; `letter-spacing` titres -.02em.
- Chiffres : `font-variant-numeric: tabular-nums` (alignement terminal).

## 4. Espacement & layout
- Base 4px. Échelle : 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96.
- Conteneur max **1200px**, gouttières `px-5` (20px) mobile.
- Rythme vertical sections : `py-20` (80px) desktop, `py-12/16` mobile.
- Rayons : cartes 16px, boutons 12px, chips 999px.
- Ombres : `soft` (profondeur cartes), `glow` (accent focalisé, parcimonie).

## 5. Composants & états
- **btn-primary** : dégradé brand, `padding .7rem 1.25rem`, hover `translateY(-1px)`
  + ombre renforcée, active `scale(.99)`, focus-visible `outline 2px brand`.
- **btn-ghost** : bordure `#232833`, hover bordure éclaircie + fond `rgba(255,255,255,.03)`.
- **card** : dégradé surface, bordure `line`, hover bordure `#2A313E`.
- **chip** : pilule bordurée, badges (« Nouveau », « Le plus populaire »).
- **nav** : sticky, `glass` (blur 14px), bordure basse ; menu mobile `x-collapse`.
- **FAQ** : accordéon Alpine (`x-collapse`), icône `+` qui pivote à 45°.

## 6. Animations & micro-interactions
- Révélation au scroll via `IntersectionObserver` (`[data-reveal]`, threshold .12).
- Flottement subtil de l'aperçu produit (`floaty`, 7s).
- Pulse discret sur l'indicateur « Temps réel ».
- Transitions `cubic-bezier(.22,.61,.36,1)`, 160–200ms.
- **Accessibilité** : `prefers-reduced-motion` coupe toutes les animations.

## 7. Responsive (mobile-first)
- **Mobile** (<768) : 1 colonne, nav burger, CTA pleine largeur, `py-12`.
- **Tablette** (md ≥768) : grilles 2 colonnes, nav complète.
- **Desktop** (lg ≥1024) : hero 2 colonnes, features/tarifs 3 colonnes, `py-20`.

## 8. Accessibilité & perf
- HTML sémantique (`header/nav/main/section/footer`), `aria-expanded` sur toggles.
- `focus-visible` visibles partout ; contrastes AA (txt/ink).
- Aucune image lourde : aperçus en SVG/CSS. Polices `display=swap`.
- Tailwind CDN + Alpine (même stack que l'app) → intégration sans build.

## 9. Intégration
- Fichier : `static/landing.html`. Servi à **`/welcome`** et **`/landing`**.
- Pour en faire la page d'accueil publique : faire pointer `/` vers
  `landing.html` et déplacer l'app vers `/app` (changement de routing à valider).
