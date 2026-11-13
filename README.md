# Discord Bot - Community Management

Bot Discord completo per la gestione di una community, sviluppato in Python con `discord.py`.

## ✨ Funzionalità

- 🎫 **Sistema Ticket** con pannello interattivo e salvataggio transcript in HTML
- 📊 **Statistiche vocali** in tempo reale (membri totali e bot)
- 🎲 **Giochi**: testa o croce (`/lancio`) e counting (`/setcounting`)
- 😂 **Meme da Reddit** (`/meme`) con cooldown
- 📢 **Annunci personalizzabili** (`/annuncio`)
- 🧹 **Clear messaggi** (`/clear`) con log
- 🎭 **Reaction Roles** configurabili (`/reactionrole`)
- 🔊 **Canali vocali temporanei** creati automaticamente
- 📝 **Log completi**: ingressi, uscite, modifiche, eliminazioni, canali, soprannomi
- 🔗 **Pannello Social** con link personalizzabili (`/social`)
- ⚙️ **Rate limiting** integrato per evitare ban dalle API

## 📋 Requisiti

- Python 3.10+
- Un bot Discord con i permessi necessari
- (Opzionale) Credenziali API Reddit per `/meme`

## 🚀 Installazione

1. Clona la repository:
```bash
git clone https://github.com/tuo-username/tuo-repo.git
cd tuo-repo
```

2. Crea un ambiente virtuale e installa le dipendenze:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

3. Copia il file `.env.example` in `.env` e compilalo con i tuoi dati:
```bash
cp .env.example .env
```

4. Avvia il bot:
```bash
python main.py
```

## ⚙️ Configurazione

Tutti gli ID (canali, ruoli, server) vanno inseriti nel file `.env`.  
Per ottenere un ID in Discord, attiva la **Modalità sviluppatore** da Impostazioni → Avanzate.

### Permessi bot necessari

Il bot richiede i seguenti **Privileged Gateway Intents**:
- `MESSAGE CONTENT INTENT`
- `SERVER MEMBERS INTENT`
- `PRESENCE INTENT` (opzionale)

Abilita questi intent nel [Discord Developer Portal](https://discord.com/developers/applications) → Bot.

## 📜 Comandi disponibili

| Comando | Descrizione | Permessi |
|---------|-------------|----------|
| `/social` | Mostra i link ai social | Tutti |
| `/annuncio` | Invia un annuncio | Amministratore |
| `/clear` | Elimina messaggi (max 100) | Amministratore |
| `/setlog` | Configura il canale dei log | Amministratore |
| `/lancio` | Gioca a testa o croce | Tutti |
| `/meme` | Mostra un meme da Reddit | Tutti |
| `/setcounting` | Imposta il canale counting | Amministratore |
| `/resetcounting` | Resetta il counting | Amministratore |
| `/startstats` | Avvia le statistiche vocali | Amministratore |
| `/stopstats` | Ferma le statistiche vocali | Amministratore |
| `/forzastats` | Aggiorna manualmente le statistiche | Amministratore |
| `/reactionrole` | Configura un reaction role | Owner |
| `/removereactionrole` | Rimuovi un reaction role | Owner |

## 📁 Struttura del progetto

```
.
├── main.py             # Codice principale del bot
├── .env.example        # Template delle variabili d'ambiente
├── .env                # Le tue credenziali (NON committare!)
├── requirements.txt    # Dipendenze Python
├── bot_data.json       # Dati persistenti (generato automaticamente)
└── README.md           # Questo file
```

## 📄 Licenza

Questo progetto è rilasciato sotto licenza MIT. Vedi il file `LICENSE` per maggiori dettagli.

## 🤝 Contributi

Le pull request sono benvenute! Per modifiche importanti, apri prima un issue per discutere cosa vorresti cambiare.