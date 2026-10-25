# RačunTracker

Self-hosted web aplikacija za račune koji stižu na Gmail (za sada mts eRačun). Sama preuzima nove račune, čita iznos, rok i poziv na broj iz mejla, PDF-a i IPS QR koda i proverava da se slažu. Račun plaćaš IPS QR kodom ili na mts sajtu, a zatim ga obeležiš kao plaćen.

Aplikacija je namenjena kućnom serveru i otvara se iz browsera na telefonu ili računaru **u kućnoj mreži**.

## Instalacija (Ubuntu 22.04, Docker)

1. Instaliraj Docker Engine i compose plugin po [zvaničnom uputstvu](https://docs.docker.com/engine/install/ubuntu/).

2. Preuzmi kod:

   ```bash
   git clone https://github.com/derdic23/racuntracker.git
   cd racuntracker
   ```

3. Napravi `.env` iz primera:

   ```bash
   cp .env.example .env
   ```

   Popuni dve obavezne vrednosti:
   - `SECRET_KEY`: dugačak nasumičan niz. Napravi ga komandom `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Njime je šifrovan Gmail app password u bazi. Ako ga kasnije promeniš, app password moraš ponovo da upišeš.
   - `APP_PASSWORD`: lozinka za prijavu u aplikaciju.

   Gmail podaci se upisuju u aplikaciji (Podešavanja), pa `GMAIL_*` u `.env` mogu da ostanu prazni.

4. Napravi folder za bazu i PDF-ove. Aplikacija u kontejneru radi kao korisnik sa UID 1000 (prvi korisnik na Ubuntu-u):

   ```bash
   mkdir -p data
   ```

   Ako tvoj korisnik nema UID 1000 (proveri sa `id -u`), prepusti folder i `.env` tom UID-u (`.env` se menja iz Podešavanja):

   ```bash
   sudo chown -R 1000:1000 data .env
   ```

5. Pokreni:

   ```bash
   docker compose up -d --build
   ```

   Aplikacija se sama pokreće posle restarta servera.

6. Nađi IP adresu servera komandom `hostname -I` (npr. `192.168.1.50`). Otvori `http://192.168.1.50:5000` sa telefona ili računara u istoj mreži. Na ruteru serveru daj stalnu adresu (DHCP rezervacija), da se adresa ne bi menjala.

7. U aplikaciji otvori **Podešavanja**:
   - **Gmail**: adresa, app password i labela. App password se pravi u Google nalogu (Bezbednost > Lozinke za aplikacije) i traži uključenu verifikaciju u dva koraka. Klikni "Testiraj vezu".
   - **Interval provere**: na koliko minuta aplikacija sama proverava mejl (podrazumevano 60, 0 isključuje). Dugme "Ažuriraj" na listi radi uvek.
   - **Profili** i **šifre korisnika**, ako računi stižu na više osoba.

## Pristup samo iz kućne mreže

Aplikacija sadrži finansijske podatke i radi preko običnog HTTP-a, bez HTTPS-a. Zato je namenjena samo kućnoj mreži:

- **Ne otvaraj port 5000 na ruteru** (port forwarding). Bez toga aplikaciji ne može da se pristupi sa interneta.
- Docker zaobilazi `ufw` pravila za objavljene portove, pa `ufw` ovde ne štiti. Ako server ima više mrežnih kartica ili javnu adresu, veži port samo za adresu u kućnoj mreži u `docker-compose.yml`:

  ```yaml
      ports:
        - "192.168.1.50:5000:5000"
  ```

- Ne povezuj server direktno na internet bez rutera.

## Održavanje

Nova verzija:

```bash
git pull
docker compose up -d --build
```

Logovi (greške automatske provere mejla se vide i na listi računa):

```bash
docker compose logs -f
```

Posle izmene `.env` (u Podešavanjima ili ručno) restartuj aplikaciju:

```bash
docker compose restart
```

Ručna provera mejla iz terminala:

```bash
docker compose exec racuntracker python cli.py fetch
```

**Rezervna kopija**: kopiraj folder `data/` (baza i PDF-ovi) i fajl `.env`. Bez istog `SECRET_KEY` sačuvani app password ne može da se pročita.

## Razvoj

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/flask --app app run --debug
```

`flask --app app run` ne pokreće automatsku proveru mejla. Nju pokreće `wsgi.py` (gunicorn u Docker-u). Server mora da radi sa jednim procesom (`--workers 1`), jer svaki proces pokreće svoju proveru.

Pravi računi i mejlovi idu samo u `samples/private/`, a baza u `data/`. Oba foldera su u `.gitignore`.
