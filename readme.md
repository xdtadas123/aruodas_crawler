# ARUODAS

## Ką daro programa

Iš nurodyto **m.aruodas.lt** paieškos URL su jau pridėtais dominančiais filtrais randą geriauius nekilnojamo turto pasiūlymus kvadratinio metro kainos toje gatvėje atžvilgiu.Pasirinktą kiekį top kandidatų įrašo į **deals_top3.txt**. Taip pat egzistuoja ir **aruodas_scrapper.py**, kuris gali pvz. užpildyti .csv visų Vilniaus butų informacija. Tokiu būdu yra prasiekiamas ir įrankis, kuriuo galima užtikrinti tiksliausius duomenis bent iš aruodas pusės. Žinoma, bendroje idėjoje egzistuoja labai labai daug tech. spragų ir logikos klaidų.

---

![Example](example.gif)

---

## Kaip gauti .exe (Windows)
1) Įdiegti priklausomybes ir Playwright Chromium:
```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

2) Sukompiliuoti C++ analizatorių:
```bash
g++ -O2 -std=c++17 -o aruodas_analyze.exe aruodas_analyzer.cpp
```

3) Supakuoti programą (PyInstaller, PowerShell):
```powershell
pyinstaller --onedir --name aruodas_app --icon app.ico `
  --add-binary "aruodas_analyze.exe;." `
  --add-data "kainos.csv;." `
  --add-data "$env:LOCALAPPDATA\ms-playwright;ms-playwright" `
  aruodas_app.py
```

4) Paleidimas:
```powershell
.\dist\aruodas_app\aruodas_app.exe
```

---

## Kaip paleisti be .exe (manual)
1) Priklausomybės + Chromium:
```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

2) C++ analizatorius:
```bash
g++ -O2 -std=c++17 -o aruodas_analyze.exe aruodas_analyzer.cpp
```

3) Paleidimas (interaktyviai):
```bash
python aruodas_app.py
```

Arba tiesiogiai (be prompt’ų):
```bash
python aruodas_search.py "<URL>" --top 10 --analyzer aruodas_analyze.exe --market-csv kainos.csv --out-top3 deals_top3.txt --append-to-market
```

---

## Kaip veikia ☝️🤓

- **aruodas_app.py**: paima `URL` ir `TOP N`, suformuoja argumentus ir kviečia `aruodas_search.main(...)`.
- **aruodas_search.py**:
  - per **Playwright** atidaro vieną naršyklės langą ir greitai pereina per „Kitas“ puslapius;
  - blokuoja `image/font/media`, kad greičiau krautų;
  - iš kiekvieno skelbimo ištraukia: `price_eur`, `eur_per_m2`, `rooms`, `area_m2`, `irengtas`, `location`, `street`;
  - naujus įrašus **appendina** į `kainos.csv` (jei įjungta `--append-to-market`);
  - surinktus skelbimus perduoda C++ analizatoriui per **STDIN** kaip CSV.
- **aruodas_analyze.exe** (C++):
  - perskaito `kainos.csv`, sugrupuoja pagal raktą (`location | street` arba tik `street` su `--street-only`);
  - kiekvienai gatvei su `n >= --min-street-n` suskaičiuoja **medianą €/m²**;
  - kiekvienam naujam skelbimui skaičiuoja `deal = street_median / listing_eur_per_m2`;
  - išrenka **TOP N** (`--top`) ir išrašo į `deals_top3.txt`.
