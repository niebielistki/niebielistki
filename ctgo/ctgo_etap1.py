#!/usr/bin/env python3
"""
CTGO – ETAP 1: paczka od Ernesta (zip) -> przesiane pliki do odesłania.

Użycie:
    python3 ctgo_etap1.py ~/Desktop/ct.zip
    python3 ctgo_etap1.py ~/Desktop/ct.zip --proc-kody 80 --nazwa CT1910

Co robi:
  1. Rozpakowuje zip hasłem CVM2026 (albo bierze już rozpakowany folder).
  2. Rozpoznaje pliki: ten z "rcs" w nazwie = RCS, drugi = plik wysyłki.
  3. Każdy plik czyści: same numery (9 cyfr, bez +48/48/0048), bez pustych
     wierszy, bez duplikatów, bez naszych numerów testowych.
     Wszystko, co odrzucone, trafia do odrzucone_*.csv z powodem.
  4. Plik wysyłki dzieli losowo: 80% -> ctgo_kody.csv (do Ernesta),
     20% -> ctgo_bezkodow.csv (zostaje u nas).
  5. Pakuje ctgo_rcs.csv + ctgo_kody.csv do zipa z hasłem (do wysłania).
  6. Wypisuje i zapisuje raport z liczbami z każdego kroku.
"""
import argparse
import csv
import datetime as dt
import random
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HASLO = "CVM2026"
FOLDER_SKRYPTU = Path(__file__).resolve().parent
PLIK_TESTOWYCH = FOLDER_SKRYPTU / "test_numbers.csv"
ROZSZERZENIA = {".txt", ".csv", ".xlsx", ".xls"}


# ---------- rozpakowanie ----------

def rozpakuj(zip_path: Path, cel: Path) -> None:
    cel.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(cel, pwd=HASLO.encode())
        return
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as e:
        blad = e  # np. szyfrowanie AES – próbujemy narzędzi systemowych
    for cmd in (["7zz", "x", f"-p{HASLO}", f"-o{cel}", "-y", str(zip_path)],
                ["7z", "x", f"-p{HASLO}", f"-o{cel}", "-y", str(zip_path)],
                ["unzip", "-o", "-P", HASLO, str(zip_path), "-d", str(cel)]):
        if shutil.which(cmd[0]):
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return
    sys.exit(f"❌ Nie udało się rozpakować {zip_path} ({blad}).\n"
             "   Jeśli zip jest szyfrowany AES: brew install sevenzip  (albo rozpakuj ręcznie i podaj folder)")


def znajdz_pliki(folder: Path):
    pliki = [p for p in folder.rglob("*")
             if p.is_file() and p.suffix.lower() in ROZSZERZENIA
             and "__MACOSX" not in p.parts and not p.name.startswith(".")]
    if len(pliki) < 2:
        sys.exit(f"❌ W {folder} są {len(pliki)} pliki z danymi, oczekiwałam 2: {[p.name for p in pliki]}")
    rcs = [p for p in pliki if "rcs" in p.name.lower()]
    reszta = [p for p in pliki if "rcs" not in p.name.lower()]
    if len(rcs) == 1 and len(reszta) == 1:
        return rcs[0], reszta[0]
    # awaryjnie: RCS to zawsze ten mniejszy
    pliki.sort(key=lambda p: p.stat().st_size)
    print(f"⚠️  Nie da się jednoznacznie rozpoznać po nazwie ({[p.name for p in pliki]}), "
          f"biorę mniejszy jako RCS: {pliki[0].name}, największy jako wysyłkę: {pliki[-1].name}")
    return pliki[0], pliki[-1]


# ---------- czytanie i czyszczenie ----------

def wiersze(path: Path):
    """Zwraca listę wierszy (tekst pierwszej kolumny / całej linii)."""
    if path.suffix.lower() in {".xlsx", ".xls"}:
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True).active
        return ["" if r[0] is None else str(r[0]) for r in ws.iter_rows(values_only=True)]
    for kod in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return path.read_text(encoding=kod).splitlines()
        except UnicodeDecodeError:
            continue


def normalizuj(tekst: str):
    s = tekst.strip().strip('"').strip("'")
    if s.endswith(".0"):  # liczby z Excela
        s = s[:-2]
    s = re.sub(r"[\s\-().]", "", s)
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("00"):
        s = s[2:]
    if len(s) == 11 and s.startswith("48"):
        s = s[2:]
    return s if re.fullmatch(r"\d{9}", s) else None


def wczytaj_testowe():
    if not PLIK_TESTOWYCH.exists():
        print(f"ℹ️  Brak {PLIK_TESTOWYCH.name} obok skryptu – nie usuwam numerów testowych.")
        return set()
    return {n for w in wiersze(PLIK_TESTOWYCH) for n in [normalizuj(w.split(",")[0].split(";")[0])] if n}


def przesiej(path: Path, testowe: set, raport: list, etykieta: str, folder_wyj: Path):
    linie = wiersze(path)
    puste = 0
    odrzucone, duplikaty, usuniete_testowe = [], 0, 0
    widziane, wynik = set(), []
    for nr, linia in enumerate(linie, 1):
        if not linia.strip():
            puste += 1
            continue
        n = normalizuj(linia)
        if n is None:
            odrzucone.append((nr, linia, "to nie jest numer telefonu"))
        elif n in testowe:
            usuniete_testowe += 1
        elif n in widziane:
            duplikaty += 1
        else:
            widziane.add(n)
            wynik.append(n)
    if odrzucone:
        with open(folder_wyj / f"odrzucone_{etykieta}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["nr_wiersza", "zawartosc", "powod"])
            w.writerows(odrzucone)
    raport += [
        f"\n[{etykieta}] plik źródłowy: {path.name}",
        f"  wierszy w pliku:          {len(linie):>10,}",
        f"  pustych wierszy:          {puste:>10,}",
        f"  odrzuconych (nie numer):  {len(odrzucone):>10,}" + ("  -> zobacz odrzucone_" + etykieta + ".csv" if odrzucone else ""),
        f"  duplikatów:               {duplikaty:>10,}",
        f"  numerów testowych:        {usuniete_testowe:>10,}",
        f"  ✅ PO PRZESIANIU:          {len(wynik):>10,}",
    ]
    return wynik


def zapisz(numery, path: Path):
    path.write_text("\n".join(numery) + "\n", encoding="utf-8")


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="CTGO etap 1: przesianie paczki i podział 80/20")
    ap.add_argument("paczka", help="zip od Ernesta albo rozpakowany folder")
    ap.add_argument("--nazwa", help="nazwa wysyłki (domyślnie nazwa zipa + data)")
    ap.add_argument("--proc-kody", type=float, default=80, help="ile %% idzie do kodów (domyślnie 80)")
    ap.add_argument("--bez-losowania", action="store_true", help="dziel po kolei zamiast losowo")
    args = ap.parse_args()

    paczka = Path(args.paczka).expanduser().resolve()
    if not paczka.exists():
        sys.exit(f"❌ Nie ma takiego pliku/folderu: {paczka}")
    dzis = dt.date.today().strftime("%Y-%m-%d")
    nazwa = args.nazwa or f"{paczka.stem}_{dzis}"
    out = FOLDER_SKRYPTU / "wysylki" / nazwa
    if out.exists() and any(out.iterdir()):
        sys.exit(f"❌ Folder {out} już istnieje – podaj inną --nazwa albo go usuń.")
    surowe = out / "0_paczka_od_ernesta"
    do_ernesta = out / "1_do_ernesta"
    u_nas = out / "2_zostaje_u_nas"
    for d in (surowe, do_ernesta, u_nas):
        d.mkdir(parents=True, exist_ok=True)

    if paczka.is_dir():
        zrodlo = paczka
    else:
        rozpakuj(paczka, surowe)
        zrodlo = surowe
    plik_rcs, plik_wys = znajdz_pliki(zrodlo)

    raport = [f"CTGO ETAP 1 – {nazwa}", f"uruchomiono: {dt.datetime.now():%Y-%m-%d %H:%M}",
              f"paczka: {paczka}"]
    testowe = wczytaj_testowe()
    rcs = przesiej(plik_rcs, testowe, raport, "rcs", out)
    wys = przesiej(plik_wys, testowe, raport, "wysylka", out)

    wspolne = len(set(rcs) & set(wys))
    raport.append(f"\n  (info) numerów jednocześnie w RCS i w wysyłce: {wspolne:,}")

    if not args.bez_losowania:
        random.shuffle(wys)
    n_kody = round(len(wys) * args.proc_kody / 100)
    kody, bez = wys[:n_kody], wys[n_kody:]

    zapisz(rcs, do_ernesta / "ctgo_rcs.csv")
    zapisz(kody, do_ernesta / "ctgo_kody.csv")
    zapisz(bez, u_nas / "ctgo_bezkodow.csv")

    raport += [
        f"\n[PODZIAŁ wysyłki {args.proc_kody:g}/{100 - args.proc_kody:g}"
        f"{'' if args.bez_losowania else ', losowo'}]",
        f"  ctgo_kody.csv     (do Ernesta): {len(kody):>10,}",
        f"  ctgo_bezkodow.csv (zostaje):    {len(bez):>10,}",
        f"  razem:                          {len(kody) + len(bez):>10,}",
        f"\n[DO WYSŁANIA ERNESTOWI] {do_ernesta}",
        f"  ctgo_rcs.csv:  {len(rcs):>10,}",
        f"  ctgo_kody.csv: {len(kody):>10,}",
    ]

    # zip z hasłem do wysyłki (zip jest wbudowany w macOS)
    zip_out = out / f"{nazwa}_do_ernesta.zip"
    if shutil.which("zip"):
        r = subprocess.run(["zip", "-j", "-q", "-P", HASLO, str(zip_out),
                            str(do_ernesta / "ctgo_rcs.csv"), str(do_ernesta / "ctgo_kody.csv")])
        raport.append(f"  📦 spakowane z hasłem {HASLO}: {zip_out.name}" if r.returncode == 0
                      else "  ⚠️ nie udało się spakować – spakuj ręcznie folder 1_do_ernesta")

    tekst = "\n".join(raport)
    (out / "raport.txt").write_text(tekst + "\n", encoding="utf-8")
    print(tekst)
    print(f"\nWszystko w: {out}")


if __name__ == "__main__":
    main()
