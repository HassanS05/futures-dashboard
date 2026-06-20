import time
from playwright.sync_api import sync_playwright
OUT="C:/Users/Administrator/Desktop/HR5 INVEST/_screens"
import os; os.makedirs(OUT, exist_ok=True)
errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    pg=b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://localhost:8000", wait_until="networkidle"); time.sleep(1)
    pg.click("text=Compte Démo"); pg.wait_for_selector(".sidebar", timeout=15000); time.sleep(4)
    SEL="document.querySelector('[x-data]')"
    d = pg.evaluate(f"() => {{ const a=Alpine.$data({SEL}); return JSON.stringify({{pfTotal:a.disp.pfTotal, real:a.pf.total_value, mcap:a.disp.mcap, vol:a.disp.vol}}); }}")
    pg.screenshot(path=f"{OUT}/dash.png", full_page=False)
    print("disp:", d)
    print("pageerrors:", errs[:6])
    b.close()
